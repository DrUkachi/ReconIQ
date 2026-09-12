import re

import pytest

from app.services.slack.events import (
    INTERACTION_ACTIONS,
    classify_event,
    classify_interaction,
    is_retry,
    is_thread_reply,
)

BOT = "U_BANKRECON"


def envelope(event: dict, **overrides) -> dict:
    base = {
        "type": "event_callback",
        "team_id": "T123",
        "event_id": "Ev123",
        "event_time": 1773000000,
        "event": event,
    }
    base.update(overrides)
    return base


def message(text="just confirmed Adeola Farms sent the 85k", **overrides) -> dict:
    base = {
        "type": "message",
        "channel": "C_OPS",
        "user": "U_TUNDE",
        "text": text,
        "ts": "1773000000.000100",
    }
    base.update(overrides)
    return base


class TestMessageRouting:
    def test_an_ordinary_channel_message_is_indexed(self):
        route = classify_event(envelope(message()), bot_user_id=BOT)
        assert route.job_kind == "index_message"

    def test_a_bot_message_is_ignored(self):
        route = classify_event(envelope(message(bot_id="B1")), bot_user_id=BOT)
        assert route.ignored and route.reason == "bot message"

    def test_our_own_message_is_ignored(self):
        """Indexing our own posts would let the agent score against itself."""
        route = classify_event(envelope(message(user=BOT)), bot_user_id=BOT)
        assert route.ignored and route.reason == "our own message"

    def test_a_short_message_is_not_indexed(self):
        route = classify_event(envelope(message(text="ok")), bot_user_id=BOT)
        assert route.ignored and "too short" in route.reason

    @pytest.mark.parametrize("subtype", ["channel_join", "channel_leave", "channel_topic"])
    def test_membership_noise_is_ignored(self, subtype):
        route = classify_event(envelope(message(subtype=subtype)), bot_user_id=BOT)
        assert route.ignored

    def test_an_edit_reindexes(self):
        route = classify_event(
            envelope(message(subtype="message_changed")), bot_user_id=BOT
        )
        assert route.job_kind == "reindex_message"

    def test_a_deletion_tombstones(self):
        route = classify_event(
            envelope(message(subtype="message_deleted")), bot_user_id=BOT
        )
        assert route.job_kind == "tombstone_message"

    def test_a_thread_reply_routes_to_the_case_handler(self):
        route = classify_event(
            envelope(message(thread_ts="1772999999.000000")), bot_user_id=BOT
        )
        assert route.job_kind == "case_thread_reply"

    def test_a_top_level_message_is_not_a_thread_reply(self):
        event = message()
        event["thread_ts"] = event["ts"]
        assert is_thread_reply(event) is False
        route = classify_event(envelope(event), bot_user_id=BOT)
        assert route.job_kind == "index_message"

    def test_a_short_thread_reply_still_reaches_the_case(self):
        """The 8 character floor guards the ambient index, not case conversation."""
        route = classify_event(
            envelope(message(text="yes", thread_ts="1772999999.000000")), bot_user_id=BOT
        )
        assert route.job_kind == "case_thread_reply"


class TestOtherEvents:
    def test_app_mention_starts_an_agent_turn(self):
        route = classify_event(
            envelope({"type": "app_mention", "user": "U_TOBI", "text": "<@B> status"}),
            bot_user_id=BOT,
        )
        assert route.job_kind == "agent_turn"

    def test_file_shared_routes_to_intake(self):
        route = classify_event(
            envelope({"type": "file_shared", "file_id": "F1", "channel_id": "C1"}),
            bot_user_id=BOT,
        )
        assert route.job_kind == "ingest_file"

    def test_the_bot_joining_a_channel_triggers_backfill(self):
        route = classify_event(
            envelope({"type": "member_joined_channel", "user": BOT, "channel": "C1"}),
            bot_user_id=BOT,
        )
        assert route.job_kind == "backfill_channel"

    def test_another_user_joining_does_not_trigger_backfill(self):
        route = classify_event(
            envelope({"type": "member_joined_channel", "user": "U_TUNDE", "channel": "C1"}),
            bot_user_id=BOT,
        )
        assert route.ignored

    def test_an_unsubscribed_event_type_is_ignored_with_a_reason(self):
        route = classify_event(envelope({"type": "reaction_added"}), bot_user_id=BOT)
        assert route.ignored and "not subscribed" in route.reason

    def test_a_non_event_envelope_is_ignored(self):
        route = classify_event({"type": "url_verification", "challenge": "x"})
        assert route.ignored


class TestRetryDetection:
    def test_retry_header_is_detected_case_insensitively(self):
        assert is_retry({"X-Slack-Retry-Num": "1"}) is True
        assert is_retry({"x-slack-retry-num": "3"}) is True
        assert is_retry({"content-type": "application/json"}) is False


class TestRouterWorkerAgreement:
    """Every kind the router can enqueue must have a handler, or jobs park as FAILED."""

    def test_every_routed_job_kind_has_a_worker_handler(self):
        import inspect

        from app.api import slack as slack_api
        from app.services.jobs.handlers import REGISTRY
        from app.services.slack import events as events_module

        sources = inspect.getsource(events_module) + inspect.getsource(slack_api)
        routed = set(re.findall(r'Route\(\s*"([a-z_]+)"', sources))
        routed |= set(re.findall(r'kind="([a-z_]+)"', sources))
        assert routed, "no routed job kinds found"

        missing = routed - set(REGISTRY)
        assert not missing, f"routed job kinds with no handler: {sorted(missing)}"


class TestInteractions:
    def base_payload(self, action_id="proposal_approve", **overrides):
        payload = {
            "type": "block_actions",
            "user": {"id": "U_AMINA"},
            "team": {"id": "T123"},
            "trigger_id": "trg-1",
            "channel": {"id": "C_RECON"},
            "message": {"ts": "1773000000.000200"},
            "actions": [{"action_id": action_id, "value": "P1"}],
        }
        payload.update(overrides)
        return payload

    def test_a_known_action_maps_to_its_handler(self):
        route = classify_interaction(self.base_payload())
        assert route.handler == "apply_resolution"
        assert route.user_slack_id == "U_AMINA"
        assert route.value == "P1"

    def test_an_unknown_action_id_is_refused_not_dispatched(self):
        """A crafted payload must not be able to reach an arbitrary handler."""
        route = classify_interaction(self.base_payload(action_id="drop_all_cases"))
        assert route.ignored and route.reason == "unknown action_id"

    def test_the_actor_comes_from_the_signed_payload_not_the_button_value(self):
        route = classify_interaction(
            self.base_payload(actions=[{"action_id": "proposal_approve", "value": "U_OWNER"}])
        )
        assert route.user_slack_id == "U_AMINA"

    def test_a_payload_with_no_actions_is_ignored(self):
        route = classify_interaction(self.base_payload(actions=[]))
        assert route.ignored

    def test_a_non_block_actions_payload_is_ignored(self):
        route = classify_interaction(self.base_payload(type="view_submission"))
        assert route.ignored

    def test_every_button_the_builders_emit_has_a_handler(self):
        """Any button rendered into Slack must be dispatchable, or it dead-ends."""
        import inspect

        from app.services.slack import blocks

        source = inspect.getsource(blocks)
        emitted = set(re.findall(r'_button\(\s*"[^"]*",\s*"([a-z_]+)"', source))
        assert emitted, "no buttons found in the builders"
        assert emitted <= set(INTERACTION_ACTIONS), (
            f"buttons with no handler: {emitted - set(INTERACTION_ACTIONS)}"
        )
