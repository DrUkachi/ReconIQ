import csv
import io
import uuid
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.infra import AuditEvent

COLUMNS = (
    "created_at",
    "action",
    "actor_slack_id",
    "case_id",
    "from_state",
    "to_state",
    "reason",
    "correlation_id",
)


async def stream_audit_csv(
    session: AsyncSession, reconciliation_id: uuid.UUID
) -> AsyncIterator[str]:
    """Streamed so a long-running period does not build the whole export in memory."""
    yield _row(COLUMNS)

    result = await session.stream(
        select(AuditEvent)
        .where(AuditEvent.reconciliation_id == reconciliation_id)
        .order_by(AuditEvent.created_at)
    )
    async for event in result.scalars():
        yield _row(
            (
                event.created_at.isoformat(),
                event.action,
                event.actor_slack_id or "",
                str(event.case_id or ""),
                event.from_state or "",
                event.to_state or "",
                event.reason or "",
                event.correlation_id or "",
            )
        )


def _row(values) -> str:
    buffer = io.StringIO()
    csv.writer(buffer).writerow(values)
    return buffer.getvalue()
