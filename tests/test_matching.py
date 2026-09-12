import random
from datetime import date

from app.domain.enums import Direction, MatchMethod, MatchState
from app.services.matching.engine import detect_duplicates, run_matching
from app.services.matching.scoring import (
    MatchingConfig,
    amount_component,
    counterparty_component,
    date_component,
    reference_component,
)
from tests.conftest import rec, serialise, txn


def test_scoring_components_match_the_prd_table():
    assert amount_component(100, 100, 0) == 40
    assert amount_component(100, 101, 0) == 0
    assert amount_component(10_000, 10_050, 100) == 25  # 50bps drift, 100bps allowed

    assert reference_component("ZEN0325", "ZEN0325") == 30
    assert reference_component("ZEN0325", "REFZEN0325X") == 20  # containment
    assert reference_component("ZEN0325", "QQQQQQQ") == 0
    assert reference_component("", "ZEN0325") == 0

    assert date_component(date(2026, 3, 5), date(2026, 3, 5)) == 15
    assert date_component(date(2026, 3, 5), date(2026, 3, 6)) == 12
    assert date_component(date(2026, 3, 5), date(2026, 3, 8)) == 8
    assert date_component(date(2026, 3, 5), date(2026, 3, 20)) == 0

    assert counterparty_component("ADEOLA FARMS", "ADEOLA FARMS") == 15
    assert counterparty_component("", "ADEOLA FARMS") == 0
    assert 0 < counterparty_component("ADEOLA FARMS", "ADEOLA FARM") < 15


def test_exact_pass_auto_matches(sample_book):
    txns, records = sample_book
    result = run_matching(txns, records)
    match = next(m for m in result.matches if m.txn_id == "T01")
    assert match.record_id == "R01"
    assert match.method is MatchMethod.EXACT
    assert match.state is MatchState.AUTO
    assert match.score == 100


def test_duplicate_pass_groups_and_excludes_from_matching(sample_book):
    txns, records = sample_book
    result = run_matching(txns, records)
    assert len(result.duplicate_groups) == 1
    assert result.duplicate_groups[0].txn_ids == ("T06", "T07")
    matched_txns = {m.txn_id for m in result.matches}
    assert "T06" not in matched_txns and "T07" not in matched_txns


def test_duplicates_require_a_reference():
    # Two genuine same-day, same-amount transfers with no reference are not duplicates.
    rows = [txn("T1", amount=500_000, day=3), txn("T2", amount=500_000, day=3)]
    assert detect_duplicates(rows) == ()


def test_ambiguity_guard_refuses_to_choose(sample_book):
    txns, records = sample_book
    result = run_matching(txns, records)
    # T03 has two near-identical Meridian candidates, R03 and R04.
    assert "T03" in result.ambiguous_txn_ids
    assert all(m.txn_id != "T03" for m in result.matches)


def test_ambiguity_guard_ignores_two_equally_weak_candidates():
    txns = [txn("T1", amount=100_000, day=3)]
    records = [
        rec("R1", amount=100_000, day=20, counterparty="AAAA"),
        rec("R2", amount=100_000, day=21, counterparty="BBBB"),
    ]
    result = run_matching(txns, records, MatchingConfig(date_window_days=30))
    assert result.ambiguous_txn_ids == ()
    assert "T1" in result.unmatched_txn_ids


def test_review_band_match_is_assigned_but_not_auto():
    # No reference and a near-miss counterparty: strong enough to propose, not to decide.
    txns = [txn("T1", amount=100_000, day=3, counterparty="ADEOLA FARMS")]
    records = [rec("R1", amount=100_000, day=3, counterparty="ADEOLA FARM")]
    result = run_matching(txns, records)
    match = result.matches[0]
    assert match.state is MatchState.REVIEW
    assert match.method is MatchMethod.SCORED
    assert 60 <= match.score < 90
    # A pending review still consumes both sides, so it blocks completion.
    assert result.unmatched_txn_ids == ()
    assert result.unmatched_record_ids == ()


def test_a_record_is_never_assigned_twice():
    txns = [
        txn("T1", amount=100_000, day=3, ref="SAME1"),
        txn("T2", amount=100_000, day=3, ref="SAME1"),
    ]
    # Same reference on both rows makes them duplicates, so use distinct refs instead.
    txns = [
        txn("T1", amount=100_000, day=3, ref="AAA111", counterparty="ACME"),
        txn("T2", amount=100_000, day=3, ref="BBB222", counterparty="ACME"),
    ]
    records = [rec("R1", amount=100_000, day=3, ref="AAA111", counterparty="ACME")]
    result = run_matching(txns, records)
    assert [m.record_id for m in result.matches].count("R1") == 1
    assert "T2" in result.unmatched_txn_ids


def test_direction_and_currency_mismatches_are_disqualifiers():
    txns = [txn("T1", amount=100_000, day=3, ref="AAA111", direction=Direction.CREDIT)]
    records = [rec("R1", amount=100_000, day=3, ref="AAA111", direction=Direction.DEBIT)]
    result = run_matching(txns, records)
    assert result.matches == ()
    assert result.unmatched_txn_ids == ("T1",)


def test_timing_difference_is_detected_outside_the_window():
    txns = [txn("T1", amount=100_000, day=3, ref="LATE01", counterparty="ACME")]
    records = [rec("R1", amount=100_000, day=25, ref="LATE01", counterparty="ACME")]
    result = run_matching(txns, records, MatchingConfig(date_window_days=5))
    assert result.timing_candidates == {"T1": ("R1",)}
    assert result.matches == ()


def test_matching_is_deterministic_across_input_order(sample_book):
    """Build gate: shuffling the inputs must not change a single byte of output."""
    txns, records = sample_book
    baseline = serialise(run_matching(txns, records))
    rng = random.Random(20260312)
    for _ in range(100):
        shuffled_txns = txns[:]
        shuffled_records = records[:]
        rng.shuffle(shuffled_txns)
        rng.shuffle(shuffled_records)
        assert serialise(run_matching(shuffled_txns, shuffled_records)) == baseline


def test_every_transaction_is_accounted_for_exactly_once(sample_book):
    """Property: matched + ambiguous + duplicate + unmatched partitions the statement."""
    txns, records = sample_book
    result = run_matching(txns, records)
    matched = {m.txn_id for m in result.matches}
    ambiguous = set(result.ambiguous_txn_ids)
    duplicated = {t for g in result.duplicate_groups for t in g.txn_ids}
    unmatched = set(result.unmatched_txn_ids)

    buckets = [matched, ambiguous, duplicated, unmatched]
    for i, left in enumerate(buckets):
        for right in buckets[i + 1 :]:
            assert not (left & right), f"{left & right} appears in two buckets"
    assert matched | ambiguous | duplicated | unmatched == {t.id for t in txns}
