# Slack intake

## Conversational replies with OpenRouter

Set `LLM_PROVIDER=openrouter`, `OPENROUTER_API_KEY`,
`OPENROUTER_API_URL=https://openrouter.ai/api/v1/chat/completions`,
`OPENROUTER_MODEL=openai/gpt-5.6-luna`, and
`OPENROUTER_REASONING_ENABLED=true` in the ignored backend `.env`. Apply migration
0004, then restart the gateway/API and worker. The key is required for model calls;
the deterministic intake workflow does not need it. No silent fallback to a different
model/provider is configured. Run `python -m scripts.check_openrouter` to verify
two real provider calls using non-financial example prompts.

In Account Team, send `@ReconIQ hello, how do I upload my files?`, then reply in
that thread with a follow-up. Questions inside an intake thread use its stored
status and per-currency summary. Chat cannot approve, close, or change financial
records; those actions are not available as model tools. Conversations are isolated
by workspace, channel and thread. Up to eight prior successful turns are included,
with any `reasoning_details` preserved unchanged in the database and subsequent
requests; Slack receives only the visible answer. Both initial and subsequent calls
send the authorization header. See [OpenRouter reasoning support](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).

To receive DMs as well, enable the `message.im` bot event and grant `im:history`.
DM chat directs uploads to Account Team. Edits, bots and unrelated channel messages
do not trigger AI replies. Repeated delivery of the same Slack message creates one
stored reply/outbox entry. Provider failures produce a safe fallback instead of
blocking intake. Structured AI extraction helpers also use OpenRouter when selected
and validate responses against their existing schemas.

In the configured Account Team channel, mention the bot:

`@ReconIQ reconcile August 2026 account 1234`

Upload the original bank PDF and ledger CSV as replies in that thread, together or in either order. For the supplied demo, use `account DEMO`. The bot asks for missing files, account, or period. It validates the five-column signed export format, imports valid sources, reconciles each currency separately, and posts results in the same thread. Processing does not close the reconciliation.

Guides/PRDs are acknowledged as context; edge-case files are validated separately and never added to the run. Rows outside the requested period remain in the source snapshot and are excluded from matching. Source files are never rewritten. Individual files are limited to 10 MiB; PDFs are limited to 50 pages.

Before processing, upload a corrected file with `replace ledger` or `replace statement` to explicitly replace a selected source. Invalid sources do not replace valid sources. Use `retry` after correcting permissions or a transient download error. Use `cancel` while waiting to cancel the intake. After processing starts, source changes are refused. A different account/period belongs in a new thread; an existing run with different sources cannot be silently overwritten.

## Local setup

1. Fill the backend `.env` using `.env.example`. Keep secrets out of tracked files and the frontend.
2. Install `requirements.txt`, run `python -m alembic upgrade head`, then run `python -m scripts.configure_slack --owner YOUR_MEMBER_ID`. This verifies the bot and the human owner with Slack before granting the local owner role. New Slack users default to Member; only Owners and Approvers can change intake.
3. In Slack app settings, merge the scopes and event subscriptions in `slack-intake-manifest.example.json` with your existing app configuration, then reinstall the app. Do not replace unrelated settings. Invite the bot to Account Team. `files:read` permits file metadata access and downloads; `channels:read` permits channel verification. Private channels additionally need `groups:read` and `groups:history`. See [Slack file permissions](https://docs.slack.dev/reference/scopes/files.read/).
4. Run `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` and, in another terminal, `python -m app.worker`.
5. Expose the backend through your HTTPS host or development tunnel and set Slack Event Subscriptions Request URL to `https://YOUR-BACKEND-HOST/slack/events`. Slack must verify this URL. Subscribe to `app_mention`, `message.channels`, `message.groups`, and `file_shared`. This implementation uses HTTP event delivery, not Socket Mode. See [Slack event delivery](https://docs.slack.dev/apis/events-api/).

### Development tunnel on this Windows machine

Use `python -m uvicorn app.slack_gateway:app --host 127.0.0.1 --port 8011` for the tunnel ingress. This small app exposes `/healthz` and the signed `/slack/events` endpoint only; application data routes and API documentation return 404. The worker still runs as `python -m app.worker`.

The official Cloudflare client is installed locally at `.local/slack/cloudflared.exe`. Start a temporary tunnel with `.local/slack/cloudflared.exe tunnel --url http://127.0.0.1:8011 --protocol http2 --no-autoupdate`. Its generated HTTPS base URL is in the tunnel output; append `/slack/events` in Slack settings. The current session saved its URL in `.local/slack/public-url.txt`, process IDs in `.local/slack/*.pid`, and logs in `.local/slack/*-out.log` / `*-error.log`. These local files are ignored by Git.

Keep this computer awake and the gateway, worker, PostgreSQL, and tunnel processes running while testing. A new quick-tunnel process generates a new URL which must be updated in Slack. This is a development connection; use a persistent host or named tunnel for ongoing operation. See [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/).

The Account Team channel is the intake boundary. Payment Ops and Treasury IDs are saved for subsequent evidence workflows; those workflows and case approval interactions are outside this intake implementation. Uploading files in those channels does not start a reconciliation.

## Verification and operational behavior

Run the full pytest suite with `RECONIQ_TEST_DATABASE_URL` pointing to a migrated, dedicated PostgreSQL test database. Without that variable, the database tests skip. The Slack tests exercise signed HTTP routing, replay protection, role/channel boundaries, both upload orders, context supplied later, source validation and correction, persisted state across handler sessions, original demo files, currency partitioning, rollback on invalid scope, and outbox pacing/retries. External Slack HTTP boundaries are replaced with controlled responses in automated tests; live credentials and owner registration are checked separately.

Incoming events acknowledge after durable enqueue, before extraction. Original bytes and file reports persist for retry recovery. Jobs and messages use idempotency keys. The outbox commits its lease before posting, throttles per channel, honors workspace rate-limit cooldown, and parks delivery after five failed attempts. An unavailable permalink does not resend an accepted message. Like any external messaging call, a crash after Slack accepts a post but before the database records success can require retry; stable client message IDs reduce duplicate risk, but delivery is not claimed to be exactly once.

Live readiness additionally requires the bot's installed scopes, channel membership, a reachable verified Request URL, and running API/worker processes. Passing local tests alone does not prove live delivery.
