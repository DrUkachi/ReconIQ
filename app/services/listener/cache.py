import uuid
from threading import Lock

from app.services.listener.scoring import CaseKeys

# PRD 6.5 step 1: the open-case key set is held in memory and invalidated on any
# case state change. Expected size is tens of cases, so listener scoring is a set
# intersection rather than a query per message.
#
# Process-local by design: the topology is one api process and one worker, and the
# worker is the only writer of listener notifications.

_cache: dict[uuid.UUID, list[CaseKeys]] = {}
_lock = Lock()


def get(workspace_id: uuid.UUID) -> list[CaseKeys] | None:
    with _lock:
        return _cache.get(workspace_id)


def put(workspace_id: uuid.UUID, keys: list[CaseKeys]) -> None:
    with _lock:
        _cache[workspace_id] = keys


def invalidate(workspace_id: uuid.UUID) -> None:
    with _lock:
        _cache.pop(workspace_id, None)


def clear() -> None:
    with _lock:
        _cache.clear()
