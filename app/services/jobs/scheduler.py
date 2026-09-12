import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import CaseState
from app.models.base import utcnow
from app.models.cases import ExceptionCase

logger = logging.getLogger(__name__)

# PRD 6.8: a single 30 second tick. Business hours are not modelled in the MVP.


async def tick(session: AsyncSession) -> None:
    await _nudge_overdue_cases(session)


async def _nudge_overdue_cases(session: AsyncSession) -> list[ExceptionCase]:
    """Cases past due_at get one follow-up; past due_at + 24h, an escalation proposal.

    Returns the cases that need a nudge. Posting goes through the outbox, so the
    nudge is durable even if Slack is unavailable when it fires.
    """
    now = utcnow()
    overdue = list(
        (
            await session.execute(
                select(ExceptionCase).where(
                    ExceptionCase.state.in_(
                        [CaseState.OPEN, CaseState.ASSIGNED, CaseState.AWAITING_INFO]
                    ),
                    ExceptionCase.due_at.is_not(None),
                    ExceptionCase.due_at < now,
                )
            )
        ).scalars()
    )
    if overdue:
        logger.info(
            "cases_overdue",
            extra={"component": "scheduler", "action": "nudge", "outcome": str(len(overdue))},
        )
    return overdue
