from dataclasses import dataclass, field
from typing import Any

from app.services.evidence.extract import is_indexable
from app.services.slack.intake_rules import is_intake_command

# PRD section 09. Routing is a pure function over the Slack envelope so the whole
# decision table is testable without HTTP, Slack, or a database.
#
# The endpoint's only job is: verify, dedupe, enqueue, return 200 inside 3 seconds.
# Everything this module decides is executed later by the worker.


@dataclass(frozen=True)
class Route:
    """What the worker should be asked to do about one Slack event.

    job_kind None means the event is deliberately ignored; `reason` says why, and
    is logged so an event that silently does nothing is still explainable.
    """

    job_kind: str | None
    payload: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    @property
    def ignored(self) -> bool:
        return self.job_kind is None


def _ignore(reason: str) -> Route:
    return Route(job_kind=None, reason=reason)


# Subtypes that are membership or housekeeping noise, never evidence.
IGNORED_MESSAGE_SUBTYPES: frozenset[str] = frozenset(
    {
        "bot_message",
        "channel_join",
        "channel_leave",
        "channel_topic",
        "channel_purpose",
        "channel_name",
        "channel_archive",
        "channel_unarchive",
        "thread_broadcast",
        "message_replied",
        "file_comment",
        "tombstone",
    }
)


def is_thread_reply(event: dict[str, Any]) -> bool:
    thread_ts = event.get("thread_ts")
    return bool(thread_ts) and thread_ts != event.get("ts")


def classify_event(envelope: dict[str, Any], *, bot_user_id: str | None = None) -> Route:
    """Map a Slack event envelope to a job.

    `bot_user_id` lets the router drop the agent's own messages, which would
    otherwise be indexed as workspace evidence and scored against open cases.
    """
    envelope_type = envelope.get("type")
    if envelope_type != "event_callback":
        return _ignore(f"envelope type {envelope_type!r} is not an event callback")

    event = envelope.get("event") or {}
    event_type = event.get("type")
    common = {
        "team_id": envelope.get("team_id"),
        "event_id": envelope.get("event_id"),
        "event_ts": envelope.get("event_time"),
    }

    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return _ignore("bot message")

    if event_type == "app_mention":
        if is_intake_command(event.get("text", "")) or event.get("files"):
            return Route("slack_intake", {**common, "event": event})
        return Route("agent_turn", {**common, "event": event, "trigger": "app_mention"})

    if event_type == "message":
        # Only messages are dropped for being ours. member_joined_channel with
        # user == the bot is precisely the event that triggers backfill.
        if bot_user_id and event.get("user") == bot_user_id:
            return _ignore("our own message")
        return _classify_message(event, common)

    if event_type == "file_shared":
        return Route("ingest_file", {**common, "event": event})

    if event_type == "app_home_opened":
        return Route("app_home", {**common, "event": event})

    if event_type == "member_joined_channel":
        # The bot joining a channel is what triggers the evidence backfill.
        if bot_user_id and event.get("user") != bot_user_id:
            return _ignore("another user joined a channel")
        return Route("backfill_channel", {**common, "event": event})

    return _ignore(f"event type {event_type!r} is not subscribed")


def _classify_message(event: dict[str, Any], common: dict[str, Any]) -> Route:
    subtype = event.get("subtype")

    # Edits and deletions keep the index honest: a case's evidence link must never
    # point at text that no longer says what it said.
    if subtype == "message_changed":
        return Route("reindex_message", {**common, "event": event})
    if subtype == "message_deleted":
        return Route("tombstone_message", {**common, "event": event})
    if subtype in IGNORED_MESSAGE_SUBTYPES:
        return _ignore(f"message subtype {subtype!r}")

    if event.get("files"):
        return Route("ingest_file", {**common, "event": event})
    if is_intake_command(event.get("text", "")) and (event.get("channel_type") == "im"):
        return Route("slack_intake", {**common, "event": event})

    # A reply inside a case thread is case work, not ambient conversation. The
    # worker resolves whether thread_ts belongs to a case; routing cannot know.
    if is_thread_reply(event):
        return Route("case_thread_reply", {**common, "event": event})

    text = event.get("text") or ""
    if not is_indexable(text):
        return _ignore("message too short to index")

    return Route("index_message", {**common, "event": event})


def is_retry(headers: dict[str, str]) -> bool:
    """Slack retries any non-200. A retry of an event we already have is a no-op."""
    lowered = {k.lower(): v for k, v in headers.items()}
    return bool(lowered.get("x-slack-retry-num"))


def retry_reason(headers: dict[str, str]) -> str:
    lowered = {k.lower(): v for k, v in headers.items()}
    return lowered.get("x-slack-retry-reason", "")


# --- interactions -----------------------------------------------------------

# Block Kit action_ids emitted by app/services/slack/blocks.py. Anything not in
# this map is rejected rather than dispatched, so a crafted payload cannot reach
# an arbitrary handler.
INTERACTION_ACTIONS: dict[str, str] = {
    "listener_attach": "attach_listener_evidence",
    "listener_dismiss": "suppress_listener_hit",
    "case_assign_self": "assign_case_self",
    "case_find_evidence": "search_case_evidence",
    "case_propose": "open_proposal_dialog",
    "case_ack": "acknowledge_case",
    "case_escalate": "propose_escalation",
    "proposal_approve": "apply_resolution",
    "proposal_reject": "reject_resolution",
}


@dataclass(frozen=True)
class InteractionRoute:
    handler: str | None
    action_id: str = ""
    value: str = ""
    user_slack_id: str = ""
    trigger_id: str = ""
    channel_id: str = ""
    message_ts: str = ""
    reason: str = ""

    @property
    def ignored(self) -> bool:
        return self.handler is None


def classify_interaction(payload: dict[str, Any]) -> InteractionRoute:
    """Map a verified Block Kit interaction to a handler.

    The acting user comes from the payload Slack signed, never from the button
    value, which is why a button cannot be used to act as someone else.
    """
    if payload.get("type") != "block_actions":
        return InteractionRoute(None, reason=f"payload type {payload.get('type')!r}")

    actions = payload.get("actions") or []
    if not actions:
        return InteractionRoute(None, reason="no actions in payload")

    action = actions[0]
    action_id = action.get("action_id", "")
    handler = INTERACTION_ACTIONS.get(action_id)
    if handler is None:
        return InteractionRoute(None, action_id=action_id, reason="unknown action_id")

    return InteractionRoute(
        handler=handler,
        action_id=action_id,
        value=action.get("value", ""),
        user_slack_id=(payload.get("user") or {}).get("id", ""),
        trigger_id=payload.get("trigger_id", ""),
        channel_id=(payload.get("channel") or {}).get("id", ""),
        message_ts=(payload.get("message") or {}).get("ts", ""),
    )
