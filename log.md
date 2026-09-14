# Handoff log

## Update: the agent routes exceptions to teams, 2026-09-14

After every run (Slack upload or `run_matching`), `enqueue_routing` queues a `route_cases`
job only if the run has unresolved exceptions; clean runs queue nothing, so no team is
messaged. The job (`app/services/cases/team_routing.py`) sends each case's facts (bank
lines, ledger records, amounts, masked long digit runs, rule label as a hint) plus the
team responsibility text in `app/services/cases/routing.py` to LLM call site
L6_CASE_ROUTING, batched 25 cases per call. HIGH/MEDIUM decisions naming a known team
with a reason are applied (`routed_by=agent`); anything else falls back to the rule table
(`routed_by=rule`), so every exception reaches exactly one team. Team, confidence and
reason are stored on the case (migration 0006), audited as CASE_ROUTED, shown in the case
thread opener, and summarised in the upload thread ("routed N exception(s) to #team (n)").
Change routing by editing TEAM_RESPONSIBILITIES; channels stay in workspace.case_channels.

Trial on the demo files with the live OpenRouter model: 38/38 cases decided by the agent
(all HIGH), 29 matched the rule table; differences were interest and FX credits to
treasury and unexplained debits to payments. 467 tests pass.

## Update: routed case threads and Resolution Status, 2026-09-13

Every unresolved case is posted as its own thread in the owning team's channel
(`app/services/cases/routing.py`): bank charges and timing differences go to
treasury; missing/unidentified payments and duplicates go to payments; amount
mismatches, ambiguous matches, extraction problems and unexplained lines go to
accounts. Channels live in `workspace.case_channels` (set with
`scripts.configure_slack --accounts-channel/--payments-channel/--treasury-channel`);
the recon channel is the fallback. Lines that nothing explains now get an
`UNMATCHED_TRANSACTION` case instead of being left without an owner.

`bank_transaction` and `payment_record` carry `resolution_status` (PENDING/RESOLVED),
`resolved_at`, `resolved_by` and `resolution_note` (migration 0005). Automatic and
confirmed matches start RESOLVED; case lines become RESOLVED only when a proposal is
approved (Slack button or web), and go back to PENDING on reopen. The API exposes
the fields on transactions and a derived `resolution_status` on cases.

A reply in a case thread is stored as unverified evidence. When the model reads it
as settling the case with a valid reason code, a proposal with Approve/Reject is posted
in the thread; otherwise the case stays Pending. Only a verified click by the assignee
or an approver (RBAC, value threshold) applies it (rule T1 unchanged). The dispatcher
records each opener's ts as the case thread.

Web sign-in looks the verified email up in installed Slack workspaces
(`users.lookupByEmail`, needs the `users:read.email` scope) and signs in as that Slack
member, so the dashboard shows Slack-run reconciliations. Other emails get a private
workspace keyed by the full address (previously by mail domain, which would have put
unrelated gmail.com users together).

Backfill existing runs with `python -m scripts.post_case_threads --dry-run`, then
without `--dry-run`; the worker sends the queued threads.

## Update: provider selection correction, 2026-09-12

Slack delivery is now confirmed: real mention events reached the worker and its
fallback message was sent successfully. The saved key was present, but effective
LLM_PROVIDER had reverted to the Anthropic default; the stored chat error was
`openrouter_not_selected`. Restored explicit OpenRouter settings in ignored `.env`,
changed the application default to OpenRouter, and separated wrong-provider and
missing-key fallback messages. The provider check now also refuses a mismatched
LLM_PROVIDER, instead of testing the transport alone.

Verification: 410 tests passed, including regression checks for the default and
accurate configuration error. Restarted the verified idle worker and confirmed
both live OpenRouter requests returned responses. A fresh Slack message is needed
to verify the new AI reply; the previous fallback delivery remains idempotently
complete. Existing gateway and tunnel were left running.

## Update: OpenRouter conversational replies, 2026-09-12

Configured provider `openrouter`, endpoint `/api/v1/chat/completions` on
openrouter.ai, and model `openai/gpt-5.6-luna` with reasoning enabled. The public
OpenRouter model catalog confirms that exact model and reasoning/structured-output
support. Existing structured helpers now select the configured provider and
validate OpenRouter JSON against their schemas. Auth is sent on every call; errors
are sanitized and OpenRouter keys are redacted in logs.

Slack mentions/questions now receive read-only AI replies through the durable
outbox. Intake commands remain deterministic. Migration 0004 persists conversation
turns with replay protection and unchanged reasoning_details for up to eight prior
successful turns in the same workspace/channel/thread; reasoning is never posted
to Slack. Intake-thread answers receive only that thread's stored status and
summary. No financial mutation tools are exposed to chat.

Verification: 408 tests passed with PostgreSQL (one dependency deprecation warning).
Migration 0004 applied to local demo/test databases. The harmless two-turn live
check is `python -m scripts.check_openrouter`. The saved key was subsequently
verified with two successful requests to the exact configured model. Both answered
the harmless strawberry question correctly. This response did not include
reasoning_details; tests verify preservation when supplied. The gateway and worker
were restarted to load the key and chat routing; the existing public HTTPS endpoint
returned health 200. No Slack messages were sent by the automated tests.

## Update: live HTTPS intake connection, 2026-09-12

Created `app.slack_gateway` exposing only health and signed Slack events, with a
focused route/authentication test passing. Started the gateway on 127.0.0.1:8011,
the background worker, and an official Cloudflare development tunnel. Runtime
logs, process IDs and current public URL are under ignored `.local/slack/`.
Verified public health 200, data/docs routes 404, unsigned event 401, and signed
verification challenge 200 with the expected response. No synthetic user events
or Slack messages were sent for this check.

Updated the supplied bot token in `.env` and local workspace configuration.
Slack now reports files:read and channels:read; bot membership is confirmed in
Account Team, Payment Ops, and Treasury. Browser automation reports no available
browser, so saving the generated Request URL and event subscriptions in Slack
has been handed to the user. A response to our signed challenge is not evidence
that Slack app settings have been saved. Await the user's confirmation/live event.

## Update: Slack intake, 2026-09-12

Implemented durable thread intake, original PDF/CSV downloads and parsing, account
and period prompts, separate context/validation files, role/channel isolation,
explicit pre-processing replacement, retry/cancel, idempotent imports/matching,
per-currency summaries, and durable outbox posting with rate-limit handling.
Migration 0003 was applied to local demo and test databases. Windows worker signal
handling and the async Slack SDK dependency are included. Setup instructions and
an example app manifest are in `docs/slack-intake.md` and
`slack-intake-manifest.example.json`.

Verification: 377 tests passed with PostgreSQL, including 35 new Slack tests.
One existing Starlette/AnyIO deprecation warning remains. Slack auth and the supplied
human member ID were verified live; the workspace and owner are registered locally.
Credentials are saved only in the ignored backend `.env` and the local workspace
configuration. No live Slack messages or uploads have been sent by this session.

Live intake still needs `files:read` and `channels:read` added to the installed app
(plus private-channel scopes where applicable), app reinstall, verified channel
membership, and a reachable Events API Request URL with API/worker processes
running. Latest scope check lacked those two scopes. Case approvals and ambient
evidence/listener handlers remain separate unfinished work; do not claim the full
product is live based on intake tests.

## Update: database import and matching, 2026-09-12

`scripts.reconcile_inputs` now commits the signed source snapshots, selected
currency/period rows, existing-engine matches, exception cases, match keys and
audit records in one transaction. `scripts/run_local_demo.ps1` runs the provisioned
Windows demo database. Source files remain unchanged. The `run_matching` worker
handler is wired and replay-safe; other previously stubbed handlers remain stubs.

The source/period uniqueness constraints now include currency. Migration 0002
upgrades existing databases; regenerated 0001 supports new databases. Two fresh
database blockers were fixed: asyncpg cannot prepare a multi-statement SQL script,
and the evidence trigram index needed an immutable text-array wrapper.

The supplied inputs produce three saved currency runs using the original matching
policy. This does not implement the guide's group matching, invoice-conflict
precedence, or alternative tolerances. Rows may still remain unmatched without
cases under the existing exception typing rules. No Slack messages are sent and
no run is marked complete automatically.

Verification: 342 tests passed with real PostgreSQL, including replay, concurrent
imports/matching, rollback, database row-reuse constraints, worker execution,
permissions and workspace isolation. Credentials and DB files are local-only in
ignored `.local/`. The earlier handoff's claim of no local Postgres is superseded.

## Update: signed source ingestion, 2026-09-12

`app/services/ingestion/` now reads the supplied five-column signed bank PDF and
ledger CSV without changing the originals. `python -m scripts.inspect_inputs`
provides a local ingestion report (see README). Raw cells, source hashes and row
locations are retained, invalid rows are reported, and matching inputs are split
by currency after applying an explicit period cutoff. This does not wire the
background jobs or persist records. The legacy debit/credit extraction path is
unchanged. Database idempotency and the demo guide's group-matching rules remain
unfinished.

Unmodified synthetic inputs are in `tests/fixtures/signed_exports/`; tests verify
57 bank rows, 52 ledger rows, per-currency control totals, two period exclusions,
and the separate ingestion fixture's 11 rejected / 5 accepted rows. Existing date
ambiguity error formatting now works on Windows as well as Unix.

The original handoff below describes the baseline before this addition.

**For:** an AI coding agent (Codex, Claude, or similar) picking this repo up cold.
**Spec:** `BANKRECON_PRD_v2.md` — ask the repo owner for it if it is not in the tree.
**Last updated:** after the Slack event router landed.

Read this file, then `README.md`. Between them you should not need to re-derive
anything. Everything below is fact about the current tree, not plan.

---

## 1. What this is

BankRecon reconciles a bank statement (PDF) against internal payment records (CSV),
groups what it cannot resolve into owned cases, and then closes those cases from the
ambient conversation of a finance team in Slack.

The distinctive part — and the thing not to break — is the **StandingCaseListener**:
open cases register standing intents, and every new workspace message is scored
against them. When a colleague mentions an invoice number in a channel, addressed to
nobody, the agent connects it to an open case unprompted.

Three data sources, and only two are trusted. Workspace claims from Slack are
**evidence only** and can never close a case without human approval. This is enforced
architecturally, not by policy — see §4.

---

## 2. Current state

```bash
pip install -r requirements.txt
python -m pytest -q        # 312 passed, ~1.5s, no database or network needed
```

**Complete and tested:** the deterministic core (extraction parsing, matching,
exception typing, listener scoring), the safety architecture, 23 database tables with
DB-enforced invariants, the REST contract (17 endpoints), and the Slack event router.

**Not yet wired:** the I/O edges. Every one is marked with `NotImplementedError` and
a one-line note saying exactly what to connect. `grep -rn NotImplementedError app/`
is your to-do list. See §6.

There is no live Postgres or Slack app in this environment. Nothing has been run
end to end against real infrastructure. Treat "tests pass" as "the logic is correct",
not "the system has been demonstrated".

---

## 3. Where things live

```
app/
  domain/       PURE value objects and logic. No I/O, no DB, no network, no LLM.
                money.py dates.py text.py records.py enums.py
  core/         config, errors (the taxonomy), rbac, logging, correlation, db
  models/       SQLAlchemy tables. Source of truth for the schema.
  services/
    extraction/ validate -> columns -> parser (pure) ; service.py does the PDF I/O
    matching/   scoring.py (components) + engine.py (passes). PURE.
    exceptions/ engine.py typing rules + grouping. PURE.
    evidence/   extract.py regex signal extraction. PURE.
    listener/   scoring.py (PURE) + cache.py (in-memory open-case key set)
    cases/      guards.py (PURE transition tables) + transitions.py (the chokepoint)
    jobs/       queue.py (leasing) handlers.py (registry) scheduler.py
    outbox/     dispatcher.py durable outbound Slack
    llm/        client.py (5 call sites) schemas.py budget.py
    slack/      verify.py (signatures) events.py (routing, PURE) blocks.py (Block Kit)
    agent/      tools.py the 14 tool contracts
  api/          deps.py (auth/idempotency) v1/routes/*.py slack.py
migrations/     0001_init.sql is GENERATED from app/models — see §5
```

**The split that matters:** anything marked PURE above takes value objects and
returns value objects. That is why 312 tests run in 1.5 seconds with no
infrastructure, and it is why the determinism gate is meaningful. Do not introduce a
database session, an HTTP client, or a model call into any of those modules. Put the
I/O in a caller and pass the results in.

---

## 4. Invariants — break these and the product's claims stop being true

These each have a test. The test names are given so you can find them.

**4.1 The deterministic core makes zero model calls.**
Matching, extraction parsing, exception typing and listener scoring never call an
LLM. `test_matching_is_deterministic_across_input_order` shuffles inputs 100 times
and asserts byte-identical output. If you add a model call to those paths, that gate
becomes a lie.

**4.2 Rule S1 — `transition_case` is the only writer of `case.state`.**
`app/services/cases/transitions.py` locks the row, checks the guard table, writes the
audit event, and invalidates the listener cache. `test_no_module_assigns_case_state_directly`
greps the whole `app/` tree to enforce this. It is verified non-vacuous: injecting
`case.state = 'CLOSED'` elsewhere makes it fail.

**4.3 Rule T1 — the model cannot reach the approval path.**
`apply_resolution`, `escalate_case` and `decide_match` have `autonomy=CONFIRM` and are
**absent from `model_tool_definitions()` entirely**. The model may only call the
`propose_*` variants. The apply path is reachable only from a verified Slack
interaction payload whose user id passes an RBAC check in code.
Tests: `TestRuleT1` in `tests/test_security.py`.

**4.4 The model can never claim an identity.**
No model-exposed tool accepts `actor_user_id`, `actor_slack_id`, `role`, or
`workspace_id`. Identity comes from the invocation context.
Test: `test_the_model_cannot_claim_an_identity_through_any_tool_argument`.

**4.5 Money is integer minor units, end to end.**
`Decimal` for parsing, never `float`. Direction comes from the debit/credit column,
never from the narration or the sign. Across the API money is always
`{minor, currency, display}`.

**4.6 RBAC is enforced in code at every call site, never in a prompt.**
The model never sees the authorisation decision. `app/core/rbac.py`, exhaustively
tested over action × role.

**4.7 Every failure is a taxonomy code.**
`app/core/errors.py`. Raise `BankReconError(ErrorCode.X, **params)`. Never raise a
bare exception to a user-facing path. Every 4xx returns `{code, message, details,
correlation_id}`.

**4.8 Side effects are ordered: commit first, then external calls.**
Outbox rows are written inside the caller's transaction. There is no code path that
calls Slack before committing.

---

## 5. Conventions you must follow

**Schema changes.** `app/models/` is the source of truth. After changing a model run
`python scripts/generate_ddl.py`, which regenerates `migrations/0001_init.sql`. The
Alembic revision executes that SQL file, so the two cannot drift. Do not hand-edit
`0001_init.sql`.

**Anthropic API — two things your training data probably has wrong:**

- **Do not send `temperature`** (or `top_p`/`top_k`). Sampling parameters were
  removed on the current model generation; sending one returns HTTP 400. The PRD's
  §08 guardrail 1 says "temperature 0 everywhere" and is **not implementable**.
  Output stability comes from `output_config: {"format": {"type": "json_schema",
  "schema": ...}}` with `additionalProperties: false`. `test_temperature_is_never_sent_because_the_api_rejects_it`
  guards this.
- **Model is `claude-sonnet-5`**, not the `claude-sonnet-4-6` in PRD §18. Same tier,
  current generation, cheaper and stronger. Configurable via `ANTHROPIC_MODEL`.
- Tools use `strict: True` with closed schemas. Thinking stays on with
  `output_config: {"effort": "low"}` rather than being disabled.

**LLM call sites are capped at five.** L1 column map, L2 counterparty, L3 evidence
summary, L4 orchestration, L5 reply intent. A sixth is a spec violation and
`test_there_are_exactly_five_call_sites` will fail. Every one has a mandatory
fallback: the system degrades, it does not error.

**Tests.** Prefer pure functions tested without fixtures over mocks. If you find
yourself mocking a database to test business logic, the logic is in the wrong module.

**Comments.** The codebase comments *why*, not *what*, and cites PRD sections where a
rule is non-obvious. Match that. Do not add narration.

---

## 6. What to do next

Ordered by dependency. Each seam has its module, contract and tests already in place.

### 6.1 Wire the job handlers (`app/services/jobs/handlers.py`)

Twelve registered kinds, each currently raising `NotImplementedError` with a note.
The Slack router already enqueues all of them. Start with:

1. `ingest_file` — fetch from `files.slack.com` (allowlist the host; §16 SSRF
   control), then `app/services/extraction/validate.py`, then enqueue
   `extract_statement`.
2. `extract_statement` — call `app.services.extraction.service.extract_statement`,
   persist `Statement` + `BankTransaction` rows **in one transaction**.
3. `run_matching` — load rows, call `run_matching`, persist `TransactionMatch`,
   then `build_cases` and persist `ExceptionCase` + `CaseMatchKey`.
4. `index_message` — `extract_signals`, write `ConversationEvidence`, enqueue
   `run_listener`.
5. `run_listener` — the headline feature. Load open-case keys (use
   `listener/cache.py`), `score_message`, then `decide_notification` for the rate
   limits, then enqueue an outbox row with `build_listener_hit`.

### 6.2 Outbox HTTP (`app/services/outbox/dispatcher.py:112`)

`_post` needs `slack_sdk.web.async_client.AsyncWebClient.chat_postMessage`.
Requirements already encoded around it: per-channel 1.1s spacing, honour
`Retry-After` on 429, retry 5xx, park as `FAILED` after 5 attempts.

### 6.3 Interaction handlers

`INTERACTION_ACTIONS` in `app/services/slack/events.py` maps nine `action_id`s to
handler names. The `interaction` job must dispatch them. **This is the only path that
reaches a confirm tool** — apply RBAC against `payload['actor_slack_id']` before
acting. `proposal_approve` → `apply_resolution` is the one that closes a case.

### 6.4 Agent orchestrator (`app/services/agent/`)

`tools.py` has the contracts; there is no `orchestrator.py` yet. Loop: assemble
context, call with `model_tool_definitions()`, execute with authorisation checks,
feed results back, max 6 turns, then `E_AGENT_TURN_BUDGET` and post what it has.
Never give it the raw statement text or another reconciliation.

### 6.5 Seed script

`make seed` and `make reset-demo` reference `scripts/seed.py`, which does not exist.
`tests/fixtures/ledger_march.csv` is there as a starting point. A realistic
Nigerian-bank statement PDF fixture is still needed (PRD §27 item 1) — a synthetic one
that looks synthetic costs marks.

### 6.6 Known gaps

- No golden-fixture test yet (PRD §20 wants `march_2026.pdf` → expected JSON, byte
  equality). Needs the statement fixture first.
- No integration or chaos tests — both need a live Postgres.
- `_cluster_words` in `extraction/service.py` (the no-ruled-table fallback) is
  untested; it needs a real PDF.
- OCR path is coded but unexercised. `ocrmypdf` is in the Dockerfile, not in this
  dev environment.

---

## 7. Decisions already made — do not silently reverse these

Each resolves a genuine ambiguity or defect in the PRD. Full reasoning is in
`README.md` under "Decisions and deviations". The two most likely to confuse you:

**Pass 1 (exact matching) applies the date window**, although §6.2's pass-1 sentence
omits it. Without the window, no pair can ever reach the `TIMING_DIFFERENCE` typing
rule (§6.3 rule 5) — that rule would be dead code. It is also the financially correct
reading: a payment booked in March that clears in April is a period-cutoff question
for a human, not an auto-match.

**Date inference refuses to guess.** A statement where every day value is ≤ 12 is
genuinely ambiguous (03/04 reads as 3 April or 4 March) and raises
`E_DATE_FORMAT_AMBIGUOUS`. `infer_date_format` accepts a `period` hint —
`ingest_statement` already takes `period_hint` — which resolves it. Do not add a
heuristic that picks one silently.

Also: duplicate detection requires a reference (amount + date alone would flag two
genuine same-day transfers); a review-band match consumes both sides and blocks
completion; counterparty scoring uses explicit half-up rounding because Python's
`round()` is banker's rounding; `case_transaction.active` makes one-open-case-per-
transaction a real database constraint.

---

## 8. Verification checklist before you commit

```bash
python -m pytest -q                    # must stay green
python scripts/generate_ddl.py         # if you touched app/models/
python -c "import app.main, app.worker" # both entrypoints must import
```

Three tests are guards rather than feature tests. If you make one fail, fix your
change — do not weaken the test:

- `test_no_module_assigns_case_state_directly` (rule S1)
- `test_model_cannot_call_apply_resolution` and the rest of `TestRuleT1`
- `test_every_routed_job_kind_has_a_worker_handler` (router/worker agreement)
