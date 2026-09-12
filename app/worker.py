import asyncio
import logging
import signal

from app.core.config import get_settings
from app.core.correlation import set_correlation_id
from app.core.db import get_sessionmaker
from app.core.logging import configure_logging
from app.services.jobs import queue

logger = logging.getLogger(__name__)

# PRD section 05: one worker process. The loop leases a job, runs its handler, and
# commits. A SIGKILL mid-run leaves the lease to expire and the job to be retried,
# which is what the chaos test exercises.

POLL_INTERVAL_SECONDS = 1.0
SCHEDULER_TICK_SECONDS = 30.0

_shutdown = asyncio.Event()


async def handle(job) -> None:
    """Dispatch a leased job to its handler.

    Handlers are registered here rather than discovered, so the set of things the
    worker can be asked to do is readable in one place.
    """
    from app.services.jobs import handlers

    handler = handlers.REGISTRY.get(job.kind)
    if handler is None:
        raise RuntimeError(f"no handler registered for job kind {job.kind!r}")
    await handler(job)


async def work_once() -> bool:
    """Lease and run one job. Returns False when the queue is empty."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        job = await queue.lease(session)
        if job is None:
            await session.commit()
            return False
        await session.commit()

    set_correlation_id(job.correlation_id)
    logger.info("job_started", extra={"component": "worker", "action": job.kind})

    async with sessionmaker() as session:
        try:
            await handle(job)
            await queue.complete(session, job.id)
            await session.commit()
            logger.info(
                "job_done", extra={"component": "worker", "action": job.kind, "outcome": "ok"}
            )
        except Exception as exc:
            await session.rollback()
            async with sessionmaker() as recovery:
                await queue.fail(recovery, job.id, str(exc))
                await recovery.commit()
            logger.exception(
                "job_failed",
                extra={
                    "component": "worker",
                    "action": job.kind,
                    "outcome": "error",
                    "error_code": type(exc).__name__,
                },
            )
    return True


async def worker_loop() -> None:
    while not _shutdown.is_set():
        try:
            busy = await work_once()
        except Exception:
            logger.exception("worker_loop_error", extra={"component": "worker"})
            busy = False
        if not busy:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def scheduler_loop() -> None:
    """PRD 6.8: follow-ups, escalation proposals, cache invalidation, lease reaping."""
    from app.services.jobs import scheduler

    while not _shutdown.is_set():
        try:
            async with get_sessionmaker()() as session:
                await queue.reap_expired_leases(session)
                await scheduler.tick(session)
                await session.commit()
        except Exception:
            logger.exception("scheduler_error", extra={"component": "scheduler"})
        await asyncio.sleep(SCHEDULER_TICK_SECONDS)


async def outbox_loop() -> None:
    """PRD 6.7: the dispatcher polls every second and leases rows like jobs."""
    from app.services.outbox import dispatcher

    while not _shutdown.is_set():
        try:
            async with get_sessionmaker()() as session:
                await dispatcher.dispatch_once(session)
                await session.commit()
        except Exception:
            logger.exception("outbox_error", extra={"component": "outbox"})
        await asyncio.sleep(1.0)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _shutdown.set)
        except NotImplementedError:  # Windows event loops
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(_shutdown.set))

    logger.info("worker_starting", extra={"component": "worker"})
    await asyncio.gather(worker_loop(), scheduler_loop(), outbox_loop())
    logger.info("worker_stopped", extra={"component": "worker"})


if __name__ == "__main__":
    asyncio.run(main())
