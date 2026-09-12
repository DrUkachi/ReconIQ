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
    raise NotImplementedError("wire to app.services.matching.engine.run_matching")


async def ingest_file(job) -> None:
    """file_shared: fetch from files.slack.com, validate, then enqueue extraction."""
    raise NotImplementedError("wire to file intake + app.services.extraction.validate")


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
    raise NotImplementedError("wire to app.services.llm.client.parse_reply_intent")


async def backfill_channel(job) -> None:
    raise NotImplementedError("wire to conversations.history backfill")


async def agent_turn(job) -> None:
    raise NotImplementedError("wire to app.services.agent.orchestrator")


async def app_home(job) -> None:
    raise NotImplementedError("wire to views.publish (P1)")


async def interaction(job) -> None:
    """Dispatch a verified Block Kit interaction.

    Rule T1: this is the only path that reaches a confirm tool, and it must apply
    RBAC against payload['actor_slack_id'] before acting.
    """
    raise NotImplementedError("wire to the interaction handlers in slack/events.py")


REGISTRY: dict[str, JobHandler] = {
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
