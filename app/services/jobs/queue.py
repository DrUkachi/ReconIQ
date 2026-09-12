import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.domain.enums import JobState
from app.models.base import utcnow
from app.models.infra import Job

# PRD section 14. Leasing with SKIP LOCKED is what makes two workers safe and what
# makes a SIGKILL mid-run recoverable: an un-completed lease simply expires.

LEASE_SECONDS = 600
MAX_ATTEMPTS = 5


async def enqueue(
    session: AsyncSession,
    *,
    kind: str,
    idempotency_key: str,
    payload: dict[str, Any] | None = None,
    workspace_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Insert unless the idempotency key already exists.

    Returns None when the job was already enqueued, which is the signal that a
    duplicate Slack delivery caused zero duplicate work.
    """
    statement = (
        insert(Job)
        .values(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            kind=kind,
            payload=payload or {},
            idempotency_key=idempotency_key,
            state=JobState.PENDING,
            correlation_id=get_correlation_id(),
            created_at=utcnow(),
        )
        .on_conflict_do_nothing(index_elements=[Job.idempotency_key])
        .returning(Job.id)
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def lease(session: AsyncSession, *, lease_seconds: int = LEASE_SECONDS) -> Job | None:
    """Claim exactly one pending job. FOR UPDATE SKIP LOCKED prevents two workers
    from picking the same row without serialising the whole queue."""
    claimed = await session.execute(
        text(
            """
            UPDATE job
               SET state = 'LEASED',
                   attempts = attempts + 1,
                   leased_until = now() + make_interval(secs => :lease_seconds)
             WHERE id = (
                   SELECT id FROM job
                    WHERE state = 'PENDING'
                    ORDER BY created_at
                      FOR UPDATE SKIP LOCKED
                    LIMIT 1)
         RETURNING id
            """
        ),
        {"lease_seconds": lease_seconds},
    )
    job_id = claimed.scalar_one_or_none()
    if job_id is None:
        return None
    return (await session.execute(select(Job).where(Job.id == job_id))).scalar_one()


async def complete(session: AsyncSession, job_id: uuid.UUID) -> None:
    await session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(state=JobState.DONE, completed_at=utcnow(), leased_until=None)
    )


async def fail(session: AsyncSession, job_id: uuid.UUID, error: str) -> None:
    """Return the job to PENDING until the attempt cap, then park it as FAILED."""
    job = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if job is None:
        return
    terminal = job.attempts >= MAX_ATTEMPTS
    job.state = JobState.FAILED if terminal else JobState.PENDING
    job.last_error = error[:2000]
    job.leased_until = None
    if terminal:
        job.completed_at = utcnow()


async def reap_expired_leases(session: AsyncSession) -> int:
    """PRD 6.8: jobs leased more than ten minutes ago return to PENDING.

    This is the mechanism behind the chaos test: SIGKILL the worker mid-matching
    and the job is retried rather than lost.
    """
    result = await session.execute(
        update(Job)
        .where(Job.state == JobState.LEASED, Job.leased_until < utcnow())
        .values(state=JobState.PENDING, leased_until=None)
    )
    return result.rowcount or 0


async def queue_depth(session: AsyncSession) -> int:
    result = await session.execute(
        select(text("count(*)")).select_from(Job).where(Job.state == JobState.PENDING)
    )
    return int(result.scalar_one())
