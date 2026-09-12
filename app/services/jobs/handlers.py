import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# Job kinds the worker can be asked to run. Registering here rather than
# discovering by import means the worker's full capability surface is one list.
#
# Every kind the Slack router can enqueue must appear here, or the job fails five
# times and parks. tests/test_slack_events.py enforces that the two sets agree.

JobHandler = Callable[[object], Awaitable[None]]


async def extract_statement(job) -> None:
    raise NotImplementedError("wire to app.services.extraction.service.extract_statement")


async def run_matching(job) -> None:
    import uuid

    from app.core.db import get_sessionmaker
    from app.core.errors import BankReconError, ErrorCode
    from app.services.matching.persistence import match_reconciliation

    try:
        reconciliation_id = uuid.UUID(str(job.payload["reconciliation_id"]))
        workspace_id = uuid.UUID(str(job.workspace_id))
    except (KeyError, ValueError, TypeError) as exc:
        raise BankReconError(ErrorCode.E_VALIDATION, detail="A matching job needs workspace and reconciliation IDs.") from exc
    async with get_sessionmaker()() as session:
        async with session.begin():
            await match_reconciliation(session, reconciliation_id=reconciliation_id, workspace_id=workspace_id)


async def ingest_file(job) -> None:
    from app.services.slack.intake import handle_intake_event
    await handle_intake_event(job)


async def process_intake(job) -> None:
    from app.services.slack.intake import process_intake as process
    await process(job)


async def index_message(job) -> None:
    """Extract signals, write conversation_evidence, then enqueue run_listener."""
    raise NotImplementedError("wire to app.services.evidence.extract.extract_signals")


async def reindex_message(job) -> None:
    """message_changed: re-extract signals for an edited message."""
    raise NotImplementedError("wire to the evidence indexer")


async def tombstone_message(job) -> None:
    """message_deleted: mark the index row deleted so evidence links never dangle."""
    raise NotImplementedError("set conversation_evidence.deleted_at")


async def run_listener(job) -> None:
    """Score one indexed message against every open case (PRD 6.5)."""
    raise NotImplementedError("wire to app.services.listener.scoring")


async def case_thread_reply(job) -> None:
    """A reply in a case thread: L5 intent parsing, then the matching action."""
    from app.core.db import get_sessionmaker
    from app.models.slack_intake import SlackIntake
    from app.models.slack_chat import SlackChatTurn
    from app.services.slack.intake_rules import is_intake_update
    from sqlalchemy import select
    event = job.payload.get("event", {})
    async with get_sessionmaker()() as session:
        intake = await session.scalar(select(SlackIntake.id).where(
            SlackIntake.workspace_id == job.workspace_id,
            SlackIntake.channel_id == event.get("channel"),
            SlackIntake.thread_ts == event.get("thread_ts")))
        chat = await session.scalar(select(SlackChatTurn.id).where(
            SlackChatTurn.workspace_id == job.workspace_id,
            SlackChatTurn.channel_id == event.get("channel"),
            SlackChatTurn.thread_ts == event.get("thread_ts")).limit(1))
    if intake:
        await (ingest_file(job) if is_intake_update(event) else agent_turn(job))
        return
    if chat:
        await agent_turn(job)
        return
    raise NotImplementedError("Case resolution replies are outside intake scope")


async def backfill_channel(job) -> None:
    raise NotImplementedError("wire to conversations.history backfill")


async def agent_turn(job) -> None:
    from app.services.slack.chat import handle_chat
    await handle_chat(job)


async def app_home(job) -> None:
    raise NotImplementedError("wire to views.publish (P1)")


async def interaction(job) -> None:
    """Dispatch a verified Block Kit interaction.

    Rule T1: this is the only path that reaches a confirm tool, and it must apply
    RBAC against payload['actor_slack_id'] before acting.
    """
    raise NotImplementedError("wire to the interaction handlers in slack/events.py")


REGISTRY: dict[str, JobHandler] = {
    "slack_intake": ingest_file,
    "process_intake": process_intake,
    "extract_statement": extract_statement,
    "run_matching": run_matching,
    "ingest_file": ingest_file,
    "index_message": index_message,
    "reindex_message": reindex_message,
    "tombstone_message": tombstone_message,
    "run_listener": run_listener,
    "case_thread_reply": case_thread_reply,
    "backfill_channel": backfill_channel,
    "agent_turn": agent_turn,
    "app_home": app_home,
    "interaction": interaction,
}
