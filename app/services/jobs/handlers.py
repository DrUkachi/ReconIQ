import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# Job kinds the worker can be asked to run. Registering here rather than
# discovering by import means the worker's full capability surface is one list.

JobHandler = Callable[[object], Awaitable[None]]


async def extract_statement(job) -> None:
    raise NotImplementedError("wire to app.services.extraction.service.extract_statement")


async def run_matching(job) -> None:
    raise NotImplementedError("wire to app.services.matching.engine.run_matching")


async def index_message(job) -> None:
    raise NotImplementedError("wire to the evidence indexer")


async def run_listener(job) -> None:
    raise NotImplementedError("wire to app.services.listener")


async def backfill_channel(job) -> None:
    raise NotImplementedError("wire to conversations.history backfill")


async def agent_turn(job) -> None:
    raise NotImplementedError("wire to app.services.agent.orchestrator")


REGISTRY: dict[str, JobHandler] = {
    "extract_statement": extract_statement,
    "run_matching": run_matching,
    "index_message": index_message,
    "run_listener": run_listener,
    "backfill_channel": backfill_channel,
    "agent_turn": agent_turn,
}
