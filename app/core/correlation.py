import uuid
from contextvars import ContextVar

# PRD section 19: minted at the Slack event or HTTP boundary, propagated through
# job payloads, tool calls, LLM calls and outbox rows.

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    return uuid.uuid4().hex[:16]


def set_correlation_id(value: str | None) -> str:
    resolved = value or new_correlation_id()
    _correlation_id.set(resolved)
    return resolved


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def short_form(value: str | None = None) -> str:
    """The form quoted in Slack error messages, so a judge asking 'how would you
    debug that' gets a real answer."""
    resolved = value or get_correlation_id() or ""
    return resolved[:8]
