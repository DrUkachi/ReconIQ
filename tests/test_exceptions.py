from app.domain.enums import CaseType, Direction, Priority
from app.services.exceptions.engine import assign_priority, build_cases
from app.services.matching.engine import run_matching
from app.services.matching.scoring import MatchingConfig
from tests.conftest import rec, txn

THRESHOLD = 50_000_000


def cases_for(txns, records, **kwargs):
    result = run_matching(txns, records, kwargs.pop("config", None))
    return build_cases(txns, records, result, value_threshold_minor=THRESHOLD, **kwargs)


def test_duplicate_case_only_counts_the_repeats_as_at_risk():
    txns = [
        txn("T1", amount=990_000, day=8, ref="DUP1X1"),
        txn("T2", amount=990_000, day=8, ref="DUP1X1"),
    ]
    drafts = cases_for(txns, [])
    duplicate = next(d for d in drafts if d.type is CaseType.DUPLICATE_BANK_ENTRY)
    assert duplicate.txn_ids == ("T1", "T2")
    assert duplicate.value_at_risk_minor == 990_000
    assert duplicate.priority is Priority.HIGH


def test_fee_lines_group_into_a_single_case():
    txns = [
        txn("T1", amount=5_000, day=3, direction=Direction.DEBIT, narration="SMS ALERT CHARGE"),
        txn("T2", amount=2_500, day=4, direction=Direction.DEBIT, narration="NIP FEE"),
        txn("T3", amount=1_000, day=5, direction=Direction.DEBIT, narration="STAMP DUTY"),
    ]
    drafts = cases_for(txns, [])
    charges = [d for d in drafts if d.type is CaseType.BANK_CHARGE_UNBOOKED]
    assert len(charges) == 1
    assert charges[0].txn_ids == ("T1", "T2", "T3")
    assert charges[0].value_at_risk_minor == 8_500


def test_unrecorded_credits_group_by_counterparty():
    txns = [
        txn("T1", amount=100_000, day=3, counterparty="ADEOLA FARMS"),
        txn("T2", amount=200_000, day=4, counterparty="ADEOLA FARMS"),
        txn("T3", amount=300_000, day=5, counterparty="KOLA LOGISTICS"),
    ]
    drafts = [d for d in cases_for(txns, []) if d.type is CaseType.MISSING_LEDGER_RECORD]
    assert len(drafts) == 2
    grouped = {d.txn_ids for d in drafts}
    assert ("T1", "T2") in grouped
    assert ("T3",) in grouped


def test_credit_with_no_resolvable_counterparty_is_unidentified():
    txns = [txn("T1", amount=100_000, day=3, narration="NIP TRF")]
    drafts = cases_for(txns, [])
    assert [d.type for d in drafts] == [CaseType.UNIDENTIFIED_CREDIT]
    assert drafts[0].priority is Priority.HIGH


def test_unmatched_debit_record_becomes_a_critical_missing_bank_entry():
    records = [rec("R1", amount=4_100_000, day=9, direction=Direction.DEBIT, ref="PAYOUT9")]
    drafts = cases_for([], records)
    assert [d.type for d in drafts] == [CaseType.MISSING_BANK_ENTRY]
    assert drafts[0].priority is Priority.CRITICAL
    assert drafts[0].record_ids == ("R1",)
    assert drafts[0].due_hours == 4


def test_ambiguous_match_produces_one_case_per_row():
    txns = [txn("T1", amount=24_000_000, day=5, counterparty="MERIDIAN")]
    records = [
        rec("R1", amount=24_000_000, day=5, counterparty="MERIDIAN HOLDINGS"),
        rec("R2", amount=24_000_000, day=5, counterparty="MERIDIAN HOLDING"),
    ]
    drafts = cases_for(txns, records)
    assert [d.type for d in drafts] == [CaseType.AMBIGUOUS_MATCH]
    assert drafts[0].priority is Priority.MEDIUM


def test_timing_difference_case_is_reachable():
    txns = [txn("T1", amount=100_000, day=3, ref="LATE01", counterparty="ACME")]
    records = [rec("R1", amount=100_000, day=25, ref="LATE01", counterparty="ACME")]
    drafts = cases_for(txns, records, config=MatchingConfig(date_window_days=5))
    assert [d.type for d in drafts] == [CaseType.TIMING_DIFFERENCE]


def test_extraction_warning_outranks_every_other_typing_rule():
    # This row would otherwise type as an unidentified credit.
    txns = [txn("T1", amount=100_000, day=3, warnings=("column_ambiguous",))]
    drafts = cases_for(txns, [])
    assert [d.type for d in drafts] == [CaseType.EXTRACTION_UNCERTAIN]


def test_extraction_uncertain_is_one_case_per_reconciliation():
    txns = [
        txn("T1", amount=100_000, day=3, warnings=("skipped",)),
        txn("T2", amount=200_000, day=4, warnings=("balance_break",)),
    ]
    drafts = [d for d in cases_for(txns, []) if d.type is CaseType.EXTRACTION_UNCERTAIN]
    assert len(drafts) == 1
    assert drafts[0].txn_ids == ("T1", "T2")


def test_balance_break_rows_are_typed_uncertain_without_a_row_warning():
    txns = [txn("T1", amount=100_000, day=3, counterparty="ADEOLA FARMS")]
    drafts = build_cases(
        txns,
        [],
        run_matching(txns, []),
        value_threshold_minor=THRESHOLD,
        balance_break_txn_ids=["T1"],
    )
    assert [d.type for d in drafts] == [CaseType.EXTRACTION_UNCERTAIN]


def test_priority_escalates_on_value_at_risk():
    assert assign_priority(CaseType.TIMING_DIFFERENCE, 1_000, THRESHOLD) is Priority.LOW
    assert assign_priority(CaseType.TIMING_DIFFERENCE, THRESHOLD, THRESHOLD) is Priority.HIGH
    assert assign_priority(CaseType.MISSING_BANK_ENTRY, 1, THRESHOLD) is Priority.CRITICAL


def test_case_building_is_deterministic(sample_book):
    txns, records = sample_book
    result = run_matching(txns, records)
    first = build_cases(txns, records, result, value_threshold_minor=THRESHOLD)
    for _ in range(50):
        assert build_cases(txns, records, result, value_threshold_minor=THRESHOLD) == first


def test_no_transaction_appears_in_two_cases(sample_book):
    txns, records = sample_book
    drafts = cases_for(txns, records)
    seen: set[str] = set()
    for draft in drafts:
        for txn_id in draft.txn_ids:
            assert txn_id not in seen, f"{txn_id} is in two cases"
            seen.add(txn_id)
