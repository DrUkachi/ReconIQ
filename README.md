# BankRecon (ReconIQ)

Reconciles a bank statement against internal payment records, groups what it cannot
resolve into owned cases, and then closes those cases from the ambient conversation
of the finance team.

Backend implementation of `BANKRECON_PRD_v2.md`. FastAPI + Postgres + Slack.

Slack intake now supports original bank PDF/ledger CSV uploads in one thread,
missing-input prompts, validation and recovery, separate currency runs, and durable
result delivery. See [Slack setup and usage](docs/slack-intake.md). Live operation
requires installed file scopes, channel membership, a verified HTTPS events URL,
and running API/worker processes.

---

## The pattern

Each unresolved exception registers a standing intent. The agent watches conversation
it was never addressed in, and when a message anywhere in its channels touches an open
case — by amount, reference, counterparty, or invoice — it surfaces the connection
unprompted, captures the message as evidence, and proposes a resolution for human approval.

Three data sources, and only two of them are trusted:

| Source | Trust | Can close a case alone |
|---|---|---|
| Bank statement (PDF) | Authoritative for what the bank did | No |
| Internal payment records (CSV) | Authoritative for what was intended | No |
| Workspace claims (Slack) | **Unverified. Evidence only.** | **Never** |

---

## Quick start

```bash
cp .env.example .env      # fill in Slack and Anthropic credentials
make up                   # db + api + worker, then migrate
make demo-check           # verify everything is green
```

API on `http://localhost:8000`, interactive docs at `/docs`.

### Inspect signed PDF and CSV exports locally

The five-column profile reads `Transaction Date`, `Transaction Reference`,
`Amount`, `Currency`, and `Transaction Text` without changing the source files.
It accepts ISO dates and signed amounts with two decimal places (positive means
cash inflow). Currency must be NGN, USD, or EUR. References retain leading zeros.

```bash
python -m scripts.inspect_inputs --bank tests/fixtures/signed_exports/Bank_Statement_Demo.pdf --ledger tests/fixtures/signed_exports/General_Ledger_Demo.csv --period-start 2026-08-01 --period-end 2026-08-31 --validation-pdf tests/fixtures/signed_exports/Ingestion_Edge_Cases_Demo.pdf
```

The JSON report includes counts, per-currency totals, validation reasons, and raw
source fields with file hashes and row locations. The optional validation PDF is
reported separately. Invalid main-input rows block preparation for matching.
Out-of-period and zero-value rows remain available but are excluded from matching
inputs. Currency groups are separate, preserving the one-currency-per-run rule.

This command validates ingestion only; it does not persist transactions, run
matching, or send Slack messages. The existing debit/credit PDF parser remains a
separate profile. The signed PDF reader requires selectable text and ruled tables
with the five headers on each page; it does not perform OCR or verify balances.
Stable source IDs support later import deduplication, but database idempotency is
not implemented by this command. Group matching and the demo guide's other matching
policy differences remain separate work.

### Persist and reconcile signed exports

With `DATABASE_URL` pointing to PostgreSQL, migrate and run:

```bash
python -m alembic upgrade head
python -m scripts.reconcile_inputs --demo --account-last4 DEMO --bank tests/fixtures/signed_exports/Bank_Statement_Demo.pdf --ledger tests/fixtures/signed_exports/General_Ledger_Demo.csv --period-start 2026-08-01 --period-end 2026-08-31
```

`--demo` creates a synthetic local workspace and owner. `DEMO` is a placeholder
account identifier, not a claim about an actual bank account. For an existing
workspace, replace `--demo` with `--workspace-id UUID --actor-id UUID`; the service
loads the actor's role from the database and requires import permissions.

The command commits source snapshots, in-period transactions, matches, cases and
audit events together. Separate currency runs share the original source hashes;
each snapshot retains all raw rows, including excluded rows. Replaying the same
files returns the existing runs. Replacing either source for the same account,
period and currency is rejected. Concurrent runs are serialized with database
row locks. The background `run_matching` handler also uses this persistence path.

Matching uses the existing PRD engine (including its five-day date window), not
the guide's alternative three-day/group-matching profile. Runs stop at
`AWAITING_ACTION`; no approvals, ledger adjustments, or Slack messages are sent.
Some residual rows remain unmatched without a case under the existing typing
rules. Slack file intake, group matching, and the full demo guide remain unfinished.

On the Windows workspace where the isolated runtime was provisioned, run
`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_local_demo.ps1`.
The execution policy applies only to that process. It starts the local database if needed and reruns
the synthetic demo. Binaries, credentials and database files stay under ignored
`.local/`; the server binds only to `127.0.0.1:55439`.

Set `RECONIQ_TEST_DATABASE_URL` to a migrated, dedicated test database to include
the PostgreSQL integration tests in `python -m pytest -q`. They cover atomic
rollback, replay, concurrency, row reuse, permissions, and workspace isolation.
Without that variable the integration tests are skipped.

Without Docker:

```bash
pip install -r requirements.txt
make test
uvicorn app.main:app --reload
```

---

## Architecture

```
Slack ──▶ verify ▶ dedupe ▶ ACK <3s ──▶ FastAPI ──▶ job queue (Postgres)
                                           │              │
   web app ◀── REST /api/v1 ───────────────┘         worker loop (leased jobs)
                                                          │
        ┌──────────┬───────────┬──────────┬───────────────┴────────┐
   Extraction   Matching   Exception   Evidence index        Orchestrator
   (det+LLM)     (det)      (det)         (det)              (LLM+tools)
        └──────────┴───────────┴──────────┴────────────────────────┘
                                │
                    Postgres ── outbox ──▶ Slack Web API
```

Three services: `db`, `api`, `worker`. No Redis, no Celery, no Kafka, no vector database.

**Why no vector DB.** Evidence matching is exact and near-exact on amounts, references,
invoice numbers, and normalised counterparty names — indexed array and trigram lookups.
Embeddings would make retrieval non-deterministic, slower, and harder to explain.

### Determinism

Matching, extraction parsing, exception typing, and listener scoring make **zero model
calls** and perform no I/O. They are pure functions over value objects in `app/domain/`,
which is why the determinism and property gates run without any infrastructure.

`test_matching_is_deterministic_across_input_order` shuffles the inputs 100 times and
asserts byte-identical serialised output. It is a build gate.

---

## Layout

```
app/
  domain/       pure value objects: money, dates, text normalisation, records
  core/         config, error taxonomy, RBAC, logging, correlation, db
  models/       SQLAlchemy tables (23) with DB-enforced invariants
  services/
    extraction/ PDF validation, column mapping, row parsing, balance continuity
    matching/   scoring components + the deterministic engine
    exceptions/ typing rules and grouping
    evidence/   regex signal extraction from workspace messages
    listener/   StandingCaseListener scoring, rate limits, suppression
    cases/      transition guards + the single transition_case chokepoint
    jobs/       leasing queue, worker handlers, scheduler
    outbox/     durable outbound Slack dispatch
    llm/        the five permitted call sites, schemas, budget
    slack/      signature verification, Block Kit builders
    agent/      tool contracts
  api/v1/       REST endpoints
migrations/     0001_init.sql (generated from models) + Alembic
```

---

## REST API

Base `/api/v1`. Auth is a session cookie; `workspace_id` is derived from the session,
**never** from a request body.

| Method | Path | Auth |
|---|---|---|
| GET | `/reconciliations` | member |
| POST | `/reconciliations` | approver |
| GET | `/reconciliations/{id}` | member |
| GET | `/reconciliations/{id}/transactions?status=&q=&cursor=` | member |
| GET | `/reconciliations/{id}/audit.csv` | approver |
| GET | `/transactions/{id}` | member |
| POST | `/transactions/{id}/decision` | approver |
| GET | `/cases?state=&assignee=&cursor=` | member |
| GET | `/cases/{id}` | member |
| POST | `/cases/{id}/assign` | per RBAC |
| POST | `/cases/{id}/evidence` | member |
| POST | `/cases/{id}/proposals` | member |
| POST | `/cases/{id}/reopen` | approver |
| POST | `/proposals/{id}/decision` | per RBAC + threshold |
| GET / PUT | `/settings` | owner |
| GET | `/healthz` `/readyz` `/metrics` | none |

**For the frontend:**

- Every mutating endpoint requires an `Idempotency-Key` header.
- Every response carries `X-Correlation-ID`; quote it in bug reports.
- Every 4xx returns `{code, message, details, correlation_id}`. `code` is from the
  error taxonomy in `app/core/errors.py` — switch on it, don't parse `message`.
- **Money is always `{minor, currency, display}`.** `minor` is an integer in minor
  units. Never do currency arithmetic in the frontend and never parse `display`.
- Evidence objects carry `verified: false` for workspace claims. **Render the
  unverified marker.** It is the safety story, not decoration.
- Case detail carries `version`; send it back on edits so a concurrent change is
  rejected rather than silently overwritten.

---

## Testing

```bash
make test
```

286 tests, no infrastructure required.

| Area | What is enforced |
|---|---|
| Money | 12 locale cases, no float drift, sign discarded (direction comes from the column) |
| Dates | File-wide format inference, >12 rule, period hint, refuses to guess |
| Matching | Component table, ambiguity guard, greedy stability, 100x determinism |
| Exceptions | All 9 typing rules, grouping, priority, no row in two cases |
| Listener | Scoring table, rate limits, suppression, the demo message |
| RBAC | Exhaustive action × role matrix, threshold escalation |
| State machines | Exhaustive over the full transition matrix |
| Security | Rule T1, prompt injection, secret redaction, signature verification |
| API | Error contract, correlation propagation, §12 surface |

Two guards worth knowing about:

- `test_no_module_assigns_case_state_directly` greps the codebase to enforce rule S1
  (`transition_case` is the only writer of `case.state`). Verified non-vacuous — it
  catches an injected violation.
- `test_the_model_cannot_claim_an_identity_through_any_tool_argument` asserts no
  model-exposed tool accepts an actor/role/workspace argument.

---

## Safety architecture

**Rule T1.** The approval path is out of band from the model. `confirm` tools
(`apply_resolution`, `escalate_case`, `decide_match`) are **not in the model's tool
list at all**. The model may only call the corresponding `propose_*` variant, which
emits a Block Kit approval. The apply path is triggered exclusively by a verified
Slack interaction payload whose user id passes the RBAC check in code.

**Blast radius.** The worst case outcome of a total compromise of the model is a
wrongly *proposed* case closure that a human must click to apply, on a system that
cannot move money, cannot write to a ledger, and cannot delete its own audit trail.

- RBAC is enforced in code at every call site, never in a prompt. The model never
  sees the RBAC decision: it proposes, code decides.
- `actor_user_id` is taken from the invocation context, never from model arguments.
- Document- and message-derived text is wrapped in `<document_content>` with a
  standing instruction that content inside is data.
- The listener is regex-driven, so a hostile message can become evidence but can
  never cause an action.
- `audit_event` has `UPDATE` and `DELETE` revoked from the app role at the database.

---

## Decisions and deviations from the PRD

These are deliberate. Each is a place the spec was ambiguous, unimplementable, or
self-defeating.

**1. `temperature: 0` is not sent (§08 guardrail 1).** Sampling parameters were
removed on the current model generation — Sonnet 5, Opus 5, and the 4.7+ family all
return HTTP 400 if `temperature` is present. Output stability instead comes from
`output_config.format`, which constrains every non-L4 call to a strict JSON schema
with `additionalProperties: false`. Nothing deterministic depends on this: matching,
extraction parsing, and the listener make zero model calls.

**2. Default model is `claude-sonnet-5`, not `claude-sonnet-4-6` (§18).** Same tier,
current generation: cheaper ($2/$10 vs $3/$15 per 1M tokens) and stronger. Override
`ANTHROPIC_MODEL` to pin the PRD value.

**3. Pass 1 (exact) applies the date window.** The spec's pass-1 sentence omits it,
but without the window no pair can ever reach the `TIMING_DIFFERENCE` typing rule
(§6.3 rule 5), which exists precisely for an exact match sitting outside the window.
Windowing is also the financially correct reading: a payment booked in March that
clears in April is a period-cutoff question for a human, not an auto-match.

**4. A transaction with more than one exact candidate is flagged ambiguous** rather
than resolved by sort order. Consistent with "I am not going to guess."

**5. Date inference accepts a period hint.** `MM/DD` variants are candidates because
the spec's own `E_DATE_FORMAT_AMBIGUOUS` message ("5 March or 3 May") only arises when
they compete. A file where every day value is ≤ 12 is genuinely ambiguous and is
refused — but `ingest_statement` already takes a `period_hint`, and a statement's rows
must fall inside the period it covers, so the hint resolves it. The error message
quotes a row the two readings actually disagree on.

**6. The evidence extractor understands `k` and `m` suffixes.** Not in the §6.4 regex,
but the headline demo beat requires "sent the 85k" to match an ₦85,000 case, and it is
how people write amounts in chat.

**7. `case_transaction` carries an `active` flag.** §11's unique index comment says
closed cases are "enforced in app". A partial unique index on `active` enforces
one-open-case-per-transaction at the database while letting a reopened period re-file
a row without destroying the historical link.

**8. A review-band match consumes both sides.** A pending review holds its transaction
and its ledger row, and blocks completion until decided.

**9. Duplicate detection requires a reference.** Grouping on amount + date alone would
report two genuine same-day ₦5,000 transfers as a duplicate.

**10. Counterparty scoring uses explicit half-up rounding.** Python's `round()` is
banker's rounding, which would make the golden fixture depend on a rule nobody reading
the PRD would expect.

---

## Status against the P0 list

| # | P0 item | State |
|---|---|---|
| 3 | Extraction, text-layer path, balance continuity | Done |
| 5 | Deterministic matching (duplicate, exact, scored, ambiguity guard) | Done |
| 6 | Exception typing and grouping | Done |
| 9 | StandingCaseListener scoring, rate limits, suppression | Scoring done; Slack wiring pending |
| 11 | Agent tool contracts + RBAC | Contracts done; orchestrator loop pending |
| 14 | Audit events, `transition_case`, guard tables | Done |
| 16 | Outbox, job leasing, error taxonomy | Durable Slack delivery, pacing, retries, leasing and taxonomy implemented |
| 1, 2 | Slack events, signing, dedupe, ACK | Signed event routing and durable thread intake implemented |
| 4 | Ledger CSV path | Fixture + schema done; loader pending |
| 7, 8 | Case threads, evidence backfill | Schema + builders done; wiring pending |
| 12, 13 | Block Kit approval, follow-up scheduler | Builders + scheduler skeleton done |
| 15 | Web workspace | Frontend, separate track |
| 17 | `make seed`, `reset-demo`, `demo-check` | `demo-check` done; seed pending |

The deterministic core, the safety architecture, the data model, and the REST contract
are complete and tested. What remains is I/O wiring: the Slack event router, the outbox
HTTP call, the agent orchestration loop, and the seed script. Each has its module and
contract in place; `NotImplementedError` marks the exact seams.

---

## Runbook

| Symptom | Action |
|---|---|
| Worker stuck | Leases expire after 10 min and jobs return to `PENDING` automatically; `reap_expired_leases` runs on the 30s tick |
| Outbox backed up | Check Slack status; rows retry to 5 attempts then park as `FAILED` and surface a banner |
| LLM down | System continues deterministically; confirm the degradation banner shows |
| Bad extraction found later | Cancel the reconciliation and re-upload; audit retains the cancelled run |
| Migrations pending | `/readyz` fails until `make migrate` runs. Never auto-migrate on boot |

`DEMO_MODE=true` changes exactly three things: scheduler timers become manually
triggerable, listener cooldowns go to 0, and the seed reset endpoint is enabled. It
does not change model behaviour, does not mock any service, and does not alter matching.
