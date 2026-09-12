import logging
import uuid
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from slack_sdk.errors import SlackApiError
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.domain.enums import OutboxState
from app.models.base import utcnow
from app.models.core import Workspace
from app.models.infra import SlackOutbox
from app.services.slack.client import slack_client

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
LEASE_SECONDS = 90


async def enqueue(
    session: AsyncSession, *, workspace_id: uuid.UUID, channel_id: str,
    builder: str, message: dict[str, Any], thread_ts: str | None = None,
    case_id: uuid.UUID | None = None, idempotency_key: str | None = None,
) -> SlackOutbox:
    values = dict(
        id=uuid.uuid4(), workspace_id=workspace_id, case_id=case_id,
        channel_id=channel_id, thread_ts=thread_ts, builder=builder,
        blocks=message.get("blocks", []), fallback_text=message.get("text", ""),
        state=OutboxState.PENDING, attempts=0, idempotency_key=idempotency_key,
        correlation_id=get_correlation_id(), created_at=utcnow(), available_at=utcnow(),
    )
    statement = insert(SlackOutbox).values(**values)
    if idempotency_key is not None:
        statement = statement.on_conflict_do_nothing(index_elements=[SlackOutbox.idempotency_key])
    inserted = (await session.execute(statement.returning(SlackOutbox.id))).scalar_one_or_none()
    if inserted is None:
        return (await session.execute(select(SlackOutbox).where(
            SlackOutbox.idempotency_key == idempotency_key,
        ))).scalar_one()
    return await session.get(SlackOutbox, inserted)


async def lease_one(session: AsyncSession) -> SlackOutbox | None:
    # Serialize the brief lease decision across dispatchers, not the HTTP call.
    if not await session.scalar(text("SELECT pg_try_advisory_xact_lock(9342216)")):
        return None
    await session.execute(text("""
        UPDATE slack_outbox SET state = CASE WHEN attempts >= :cap THEN 'FAILED' ELSE 'PENDING' END,
            leased_until = NULL, last_error = 'delivery_lease_expired'
        WHERE state = 'LEASED' AND leased_until < clock_timestamp()
    """), {"cap": MAX_ATTEMPTS})
    row_id = await session.scalar(text("""
        UPDATE slack_outbox SET state='LEASED', attempts=attempts+1,
            leased_until=clock_timestamp()+make_interval(secs => :lease)
        WHERE id = (
            SELECT o.id FROM slack_outbox o JOIN workspace w ON w.id=o.workspace_id
            WHERE o.state='PENDING' AND o.available_at<=clock_timestamp()
              AND (w.slack_retry_at IS NULL OR w.slack_retry_at<=clock_timestamp())
              AND w.uninstalled_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM slack_outbox earlier
                  WHERE earlier.workspace_id=o.workspace_id AND earlier.channel_id=o.channel_id
                    AND earlier.state IN ('PENDING','LEASED')
                    AND (earlier.created_at,earlier.id)<(o.created_at,o.id))
              AND NOT EXISTS (
                  SELECT 1 FROM slack_outbox active
                  WHERE active.workspace_id=o.workspace_id AND active.channel_id=o.channel_id
                    AND (active.state='LEASED' OR active.sent_at > clock_timestamp()-interval '1.1 seconds'))
            ORDER BY o.created_at,o.id LIMIT 1 FOR UPDATE OF o SKIP LOCKED
        ) RETURNING id
    """), {"lease": LEASE_SECONDS})
    return await session.get(SlackOutbox, row_id, populate_existing=True) if row_id else None


async def dispatch_once(session: AsyncSession, client=None) -> bool:
    row = await lease_one(session)
    if row is None:
        await session.commit()
        return False
    workspace = await session.get(Workspace, row.workspace_id)
    delivery = SimpleNamespace(
        id=row.id, workspace_id=row.workspace_id, channel_id=row.channel_id,
        thread_ts=row.thread_ts, blocks=row.blocks, fallback_text=row.fallback_text,
        attempts=row.attempts, leased_until=row.leased_until,
    )
    token = workspace.bot_token or ""
    # Outbound side effects can only observe an already committed lease/outbox.
    await session.commit()
    values = {"leased_until": None}
    try:
        response = await _post(delivery, client or slack_client(token))
        values.update(state=OutboxState.SENT, message_ts=response["ts"],
                      permalink=response.get("permalink"), sent_at=utcnow(), last_error=None)
    except Exception as exc:
        code, retry_after = _failure(exc, delivery.attempts)
        retry_at = utcnow() + timedelta(seconds=retry_after)
        values.update(state=OutboxState.FAILED if delivery.attempts >= MAX_ATTEMPTS else OutboxState.PENDING,
                      last_error=code, available_at=retry_at)
        if isinstance(exc, SlackApiError) and exc.response.status_code == 429:
            await session.execute(update(Workspace).where(Workspace.id == delivery.workspace_id).values(slack_retry_at=retry_at))
        logger.warning("outbox_post_failed", extra={"component": "outbox", "error_code": code})
    await session.execute(update(SlackOutbox).where(
        SlackOutbox.id == delivery.id, SlackOutbox.state == OutboxState.LEASED,
        SlackOutbox.leased_until == delivery.leased_until,
    ).values(**values))
    await session.commit()
    return True


def _failure(exc: Exception, attempts: int) -> tuple[str, int]:
    if isinstance(exc, SlackApiError):
        if exc.response.status_code == 429:
            headers = {k.lower(): v for k, v in exc.response.headers.items()}
            try:
                value = headers.get("retry-after", "1")
                return "slack_rate_limited", max(1, int(value[0] if isinstance(value, list) else value))
            except (TypeError, ValueError):
                return "slack_rate_limited", 60
        return str(exc.response.get("error", "slack_api_error"))[:80], min(60, 2 ** attempts)
    return type(exc).__name__, min(60, 2 ** attempts)


async def _post(row, client) -> dict[str, Any]:
    response = await client.chat_postMessage(
        channel=row.channel_id, thread_ts=row.thread_ts, text=row.fallback_text,
        blocks=row.blocks or None, client_msg_id=str(row.id),
        parse="none", link_names=False, unfurl_links=False, unfurl_media=False,
    )
    result = {"ts": response["ts"]}
    try:
        link = await client.chat_getPermalink(conversation_id=row.channel_id, message_ts=response["ts"])
        result["permalink"] = link.get("permalink")
    except Exception:
        # A permalink failure must not resend a message Slack already accepted.
        logger.info("outbox_permalink_unavailable", extra={"component": "outbox"})
    return result


async def depth(session: AsyncSession) -> int:
    result = await session.execute(select(text("count(*)")).select_from(SlackOutbox).where(
        SlackOutbox.state == OutboxState.PENDING,
    ))
    return int(result.scalar_one())
