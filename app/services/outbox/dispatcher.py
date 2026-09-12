import logging
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.domain.enums import OutboxState
from app.models.base import utcnow
from app.models.infra import SlackOutbox

logger = logging.getLogger(__name__)

# PRD 6.7. Every outbound Slack call goes through this table. State is never
# contingent on a successful post: the reconciliation is correct whether or not
# Slack is reachable.

MAX_ATTEMPTS = 5
LEASE_SECONDS = 60


async def enqueue(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    channel_id: str,
    builder: str,
    message: dict[str, Any],
    thread_ts: str | None = None,
    case_id: uuid.UUID | None = None,
) -> SlackOutbox:
    """Insert the outbound message as part of the caller's transaction (rule C1).

    There is no code path that calls Slack before committing.
    """
    row = SlackOutbox(
        workspace_id=workspace_id,
        case_id=case_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
        builder=builder,
        blocks=message.get("blocks", []),
        fallback_text=message.get("text", ""),
        state=OutboxState.PENDING,
        correlation_id=get_correlation_id(),
        created_at=utcnow(),
    )
    session.add(row)
    await session.flush()
    return row


async def lease_one(session: AsyncSession) -> SlackOutbox | None:
    claimed = await session.execute(
        text(
            """
            UPDATE slack_outbox
               SET state = 'LEASED',
                   attempts = attempts + 1,
                   leased_until = now() + make_interval(secs => :lease_seconds)
             WHERE id = (
                   SELECT id FROM slack_outbox
                    WHERE state = 'PENDING'
                    ORDER BY created_at
                      FOR UPDATE SKIP LOCKED
                    LIMIT 1)
         RETURNING id
            """
        ),
        {"lease_seconds": LEASE_SECONDS},
    )
    row_id = claimed.scalar_one_or_none()
    if row_id is None:
        return None
    return (
        await session.execute(select(SlackOutbox).where(SlackOutbox.id == row_id))
    ).scalar_one()


async def dispatch_once(session: AsyncSession, client=None) -> bool:
    """Send at most one queued message. Returns False when the outbox is empty."""
    row = await lease_one(session)
    if row is None:
        return False

    try:
        result = await _post(row, client)
        row.message_ts = result.get("ts")
        row.permalink = result.get("permalink")
        row.state = OutboxState.SENT
        row.sent_at = utcnow()
        row.leased_until = None
    except Exception as exc:
        row.last_error = str(exc)[:2000]
        row.leased_until = None
        # Permanent failure after five attempts surfaces a banner in the web app.
        row.state = OutboxState.FAILED if row.attempts >= MAX_ATTEMPTS else OutboxState.PENDING
        logger.warning(
            "outbox_post_failed",
            extra={
                "component": "outbox",
                "action": row.builder,
                "outcome": str(row.state),
                "error_code": type(exc).__name__,
            },
        )
    return True


async def _post(row: SlackOutbox, client=None) -> dict[str, Any]:
    raise NotImplementedError(
        "wire to slack_sdk AsyncWebClient.chat_postMessage with per-channel 1.1s spacing"
    )


async def depth(session: AsyncSession) -> int:
    result = await session.execute(
        select(text("count(*)")).select_from(SlackOutbox).where(
            SlackOutbox.state == OutboxState.PENDING
        )
    )
    return int(result.scalar_one())
