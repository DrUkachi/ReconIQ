from datetime import datetime, timedelta, timezone

from app.domain.records import EvidenceMessage
from app.services.evidence.extract import (
    extract_amounts,
    extract_signals,
    is_indexable,
)
from app.services.listener.scoring import (
    CaseKeys,
    ListenerConfig,
    decide_notification,
    score_message,
    trigram_similarity,
)

CASE_CREATED = datetime(2026, 3, 12, 9, 0, tzinfo=timezone.utc)
LATER = CASE_CREATED + timedelta(hours=2)


def case_keys(**kwargs) -> CaseKeys:
    base = dict(
        case_id="C1",
        created_at=CASE_CREATED,
        amounts_minor=frozenset({8_500_000}),
        refs_norm=frozenset({"ZEN0325887711"}),
        invoices=frozenset({"INV-41"}),
        counterparties=frozenset({"ADEOLA FARMS"}),
    )
    base.update(kwargs)
    return CaseKeys(**base)


def message(text_signals: dict, *, author="U_TUNDE", posted_at=LATER) -> EvidenceMessage:
    return EvidenceMessage(
        id="E1",
        channel_id="C_OPS",
        author_slack_id=author,
        ts="1773000000.000100",
        posted_at=posted_at,
        excerpt="",
        amounts_minor=text_signals.get("amounts_minor", ()),
        refs_norm=text_signals.get("refs_norm", ()),
        invoices=text_signals.get("invoices", ()),
        counterparties=text_signals.get("counterparties", ()),
    )


def test_the_demo_message_clears_the_threshold():
    """The headline beat: a message addressed to nobody connects to an open case."""
    text = "just confirmed Adeola Farms sent the 85k, ref ZEN0325887711"
    signals = extract_signals(text)
    score = score_message(case_keys(), message(signals))
    assert score is not None
    assert score.score >= ListenerConfig().threshold
    assert any("ZEN0325887711" in m for m in score.matched_on)


def test_reference_alone_clears_the_threshold():
    score = score_message(case_keys(), message({"refs_norm": ("ZEN0325887711",)}))
    assert score is not None and score.score == 60


def test_amount_alone_does_not_clear_the_threshold():
    score = score_message(case_keys(), message({"amounts_minor": (8_500_000,)}))
    assert score is not None and score.score == 35
    decision = decide_notification(
        score=score.score,
        notifications_for_case=0,
        last_notified_at=None,
        workspace_notifications_last_hour=0,
        suppressed=False,
        now=LATER,
    )
    assert decision.notify is False and decision.reason == "below_threshold"


def test_assignee_authorship_adds_ten():
    keys = case_keys(assignee_slack_id="U_TUNDE")
    score = score_message(keys, message({"amounts_minor": (8_500_000,)}, author="U_TUNDE"))
    assert score is not None and score.score == 45


def test_a_message_predating_the_case_is_discarded():
    earlier = CASE_CREATED - timedelta(minutes=1)
    score = score_message(
        case_keys(), message({"refs_norm": ("ZEN0325887711",)}, posted_at=earlier)
    )
    assert score is None


def test_an_unrelated_message_scores_nothing():
    assert score_message(case_keys(), message({"refs_norm": ("QQQ999",)})) is None


def test_invoice_match_scores_fifty_five():
    score = score_message(case_keys(), message({"invoices": ("INV-41",)}))
    assert score is not None and score.score == 55


def test_counterparty_needs_trigram_agreement():
    close = score_message(case_keys(), message({"counterparties": ("ADEOLA FARM",)}))
    assert close is not None and close.score == 20
    far = score_message(case_keys(), message({"counterparties": ("KOLA LOGISTICS",)}))
    assert far is None


def test_trigram_similarity_is_bounded_and_symmetric():
    assert trigram_similarity("ADEOLA FARMS", "ADEOLA FARMS") == 1.0
    assert trigram_similarity("", "ADEOLA") == 0.0
    assert trigram_similarity("ADEOLA", "AXXXXX") < 0.75
    assert trigram_similarity("ADEOLA FARMS", "ADEOLA FARM") == trigram_similarity(
        "ADEOLA FARM", "ADEOLA FARMS"
    )


def test_listener_scoring_is_deterministic():
    signals = extract_signals("Adeola Farms sent the 85k, ref ZEN0325887711 for INV-41")
    keys, msg = case_keys(), message(signals)
    first = score_message(keys, msg)
    for _ in range(100):
        assert score_message(keys, msg) == first


class TestRateLimits:
    """PRD 6.5 step 5. Every limit stores the evidence silently rather than dropping it."""

    def test_cooldown_suppresses_a_second_post_within_six_hours(self):
        decision = decide_notification(
            score=90,
            notifications_for_case=1,
            last_notified_at=LATER - timedelta(hours=1),
            workspace_notifications_last_hour=0,
            suppressed=False,
            now=LATER,
        )
        assert decision.notify is False and decision.reason == "case_cooldown"

    def test_cooldown_expires(self):
        decision = decide_notification(
            score=90,
            notifications_for_case=1,
            last_notified_at=LATER - timedelta(hours=7),
            workspace_notifications_last_hour=0,
            suppressed=False,
            now=LATER,
        )
        assert decision.notify is True

    def test_three_notifications_per_case_is_the_hard_cap(self):
        decision = decide_notification(
            score=90,
            notifications_for_case=3,
            last_notified_at=None,
            workspace_notifications_last_hour=0,
            suppressed=False,
            now=LATER,
        )
        assert decision.notify is False and decision.reason == "case_notification_cap"

    def test_workspace_hourly_cap(self):
        decision = decide_notification(
            score=90,
            notifications_for_case=0,
            last_notified_at=None,
            workspace_notifications_last_hour=10,
            suppressed=False,
            now=LATER,
        )
        assert decision.notify is False and decision.reason == "workspace_hourly_cap"

    def test_not_related_suppression_wins_over_everything(self):
        decision = decide_notification(
            score=100,
            notifications_for_case=0,
            last_notified_at=None,
            workspace_notifications_last_hour=0,
            suppressed=True,
            now=LATER,
        )
        assert decision.notify is False and decision.reason == "suppressed_by_not_related"


class TestEvidenceExtraction:
    def test_currency_marked_amounts(self):
        assert extract_amounts("we paid ₦85,000.00 yesterday") == (8_500_000,)
        assert extract_amounts("NGN 1,200") == (120_000,)

    def test_k_and_m_suffixes(self):
        assert extract_amounts("sent the 85k") == (8_500_000,)
        assert extract_amounts("paid 2.5m for the haulage") == (250_000_000,)

    def test_bare_numbers_need_a_payment_verb(self):
        assert extract_amounts("the invoice is 85000 naira") == ()
        assert extract_amounts("we paid 85000") == (8_500_000,)

    def test_references_need_a_digit_and_a_letter(self):
        signals = extract_signals("ref ZEN0325887711 and 12345678 and ABCDEFGH")
        assert "ZEN0325887711" in signals["refs_norm"]
        assert "12345678" not in signals["refs_norm"]
        assert "ABCDEFGH" not in signals["refs_norm"]

    def test_invoices_are_normalised(self):
        for text in ("INV-41", "INV/41", "INV 41", "inv41"):
            assert extract_signals(text)["invoices"] == ("INV-41",)

    def test_short_and_bot_messages_are_not_indexed(self):
        assert is_indexable("ok") is False
        assert is_indexable("a longer message", is_bot=True) is False
        assert is_indexable("a longer message") is True
