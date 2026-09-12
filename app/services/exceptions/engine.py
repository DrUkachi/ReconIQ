from collections import defaultdict
from typing import Iterable, Sequence

from app.domain.enums import (
    PRIORITY_DUE_HOURS,
    CaseType,
    Direction,
    MatchKeyType,
    Priority,
)
from app.domain.money import format_minor
from app.domain.records import BankTxn, CaseDraft, MatchingResult, PaymentRecord
from app.domain.text import extract_invoices, is_fee_narration

# PRD 6.3. Deterministic typing and grouping over the residuals of matching.

HIGH_PRIORITY_TYPES: frozenset[CaseType] = frozenset(
    {
        CaseType.DUPLICATE_BANK_ENTRY,
        CaseType.MISSING_LEDGER_RECORD,
        CaseType.UNIDENTIFIED_CREDIT,
    }
)

MEDIUM_PRIORITY_TYPES: frozenset[CaseType] = frozenset(
    {
        CaseType.AMBIGUOUS_MATCH,
        CaseType.AMOUNT_MISMATCH,
        CaseType.EXTRACTION_UNCERTAIN,
    }
)


def assign_priority(case_type: CaseType, value_at_risk_minor: int, threshold_minor: int) -> Priority:
    if case_type is CaseType.MISSING_BANK_ENTRY:
        return Priority.CRITICAL
    if value_at_risk_minor >= threshold_minor or case_type in HIGH_PRIORITY_TYPES:
        return Priority.HIGH
    if case_type in MEDIUM_PRIORITY_TYPES:
        return Priority.MEDIUM
    return Priority.LOW


def type_transaction(
    txn: BankTxn,
    result: MatchingResult,
    *,
    duplicated: frozenset[str],
    uncertain: frozenset[str],
) -> CaseType | None:
    """PRD 6.3 typing table. Evaluated in order; first match wins."""
    if txn.id in duplicated:
        return CaseType.DUPLICATE_BANK_ENTRY
    if txn.id in uncertain:
        return CaseType.EXTRACTION_UNCERTAIN
    if txn.id in result.ambiguous_txn_ids:
        return CaseType.AMBIGUOUS_MATCH

    candidates = result.candidates_by_txn.get(txn.id, ())
    best = candidates[0] if candidates else None
    if best is not None and best.score >= 60 and best.breakdown.amount < 40:
        return CaseType.AMOUNT_MISMATCH
    if txn.id in result.timing_candidates:
        return CaseType.TIMING_DIFFERENCE
    if not candidates:
        if txn.direction is Direction.DEBIT and is_fee_narration(txn.narration):
            return CaseType.BANK_CHARGE_UNBOOKED
        if txn.direction is Direction.CREDIT:
            return (
                CaseType.MISSING_LEDGER_RECORD
                if txn.counterparty_norm
                else CaseType.UNIDENTIFIED_CREDIT
            )
    return None


def build_cases(
    txns: Sequence[BankTxn],
    records: Sequence[PaymentRecord],
    result: MatchingResult,
    *,
    value_threshold_minor: int,
    balance_break_txn_ids: Iterable[str] = (),
) -> tuple[CaseDraft, ...]:
    txn_by_id = {t.id: t for t in txns}
    record_by_id = {r.id: r for r in records}

    duplicated = frozenset(tid for g in result.duplicate_groups for tid in g.txn_ids)
    uncertain = frozenset(
        [t.id for t in txns if t.warnings] + [str(i) for i in balance_break_txn_ids]
    )

    residual_ids = set(result.unmatched_txn_ids) | set(result.ambiguous_txn_ids) | duplicated | (
        uncertain & set(txn_by_id)
    )
    typed: dict[CaseType, list[BankTxn]] = defaultdict(list)
    for txn_id in sorted(residual_ids):
        txn = txn_by_id.get(txn_id)
        if txn is None:
            continue
        case_type = type_transaction(
            txn, result, duplicated=duplicated, uncertain=uncertain
        )
        if case_type is not None:
            typed[case_type].append(txn)

    drafts: list[CaseDraft] = []

    for group in result.duplicate_groups:
        members = [txn_by_id[tid] for tid in group.txn_ids if tid in txn_by_id]
        if len(members) < 2:
            continue
        # Only the repeats are at risk; the first posting is presumed legitimate.
        at_risk = sum(t.amount_minor for t in members[1:])
        drafts.append(
            _draft(
                CaseType.DUPLICATE_BANK_ENTRY,
                members,
                at_risk,
                value_threshold_minor,
                title=f"Duplicate bank entry: {format_minor(members[0].amount_minor, members[0].currency)}",
                summary=(
                    f"{len(members)} statement lines share amount, value date and "
                    f"reference {members[0].reference_norm}."
                ),
            )
        )

    uncertain_rows = typed.get(CaseType.EXTRACTION_UNCERTAIN, [])
    if uncertain_rows:
        drafts.append(
            _draft(
                CaseType.EXTRACTION_UNCERTAIN,
                uncertain_rows,
                sum(t.amount_minor for t in uncertain_rows),
                value_threshold_minor,
                title=f"Extraction uncertain on {len(uncertain_rows)} line(s)",
                summary=(
                    "These lines carry a parse warning or sit inside a balance-continuity "
                    "break. Reconciliation cannot complete until they are confirmed."
                ),
            )
        )

    charges = typed.get(CaseType.BANK_CHARGE_UNBOOKED, [])
    if charges:
        drafts.append(
            _draft(
                CaseType.BANK_CHARGE_UNBOOKED,
                charges,
                sum(t.amount_minor for t in charges),
                value_threshold_minor,
                title=f"{len(charges)} unbooked bank charge(s)",
                summary="Fee lines on the statement with no matching ledger record.",
            )
        )

    for case_type in (CaseType.MISSING_LEDGER_RECORD, CaseType.UNIDENTIFIED_CREDIT):
        for members in _group_by_counterparty(typed.get(case_type, [])):
            counterparty = members[0].counterparty_norm or "unidentified sender"
            drafts.append(
                _draft(
                    case_type,
                    members,
                    sum(t.amount_minor for t in members),
                    value_threshold_minor,
                    title=(
                        f"{len(members)} unrecorded credit(s) from {counterparty}"
                        if case_type is CaseType.MISSING_LEDGER_RECORD
                        else f"Unidentified credit {format_minor(members[0].amount_minor, members[0].currency)}"
                    ),
                    summary=(
                        "Money arrived that the ledger does not explain."
                        if case_type is CaseType.MISSING_LEDGER_RECORD
                        else "Money arrived from a sender the narration does not resolve."
                    ),
                )
            )

    for case_type in (
        CaseType.AMBIGUOUS_MATCH,
        CaseType.AMOUNT_MISMATCH,
        CaseType.TIMING_DIFFERENCE,
    ):
        for txn in typed.get(case_type, []):
            drafts.append(
                _draft(
                    case_type,
                    [txn],
                    txn.amount_minor,
                    value_threshold_minor,
                    title=_single_title(case_type, txn),
                    summary=_single_summary(case_type, txn, result),
                )
            )

    for record_id in result.unmatched_record_ids:
        record = record_by_id.get(record_id)
        if record is None or record.direction is not Direction.DEBIT:
            continue
        drafts.append(
            CaseDraft(
                type=CaseType.MISSING_BANK_ENTRY,
                priority=assign_priority(
                    CaseType.MISSING_BANK_ENTRY, record.amount_minor, value_threshold_minor
                ),
                title=(
                    f"Payment recorded but not on the statement: "
                    f"{format_minor(record.amount_minor, record.currency)}"
                ),
                summary=(
                    f"Ledger record {record.external_id or record.id} dated "
                    f"{record.record_date.isoformat()} has no corresponding bank line."
                ),
                txn_ids=(),
                record_ids=(record.id,),
                value_at_risk_minor=record.amount_minor,
                due_hours=PRIORITY_DUE_HOURS[Priority.CRITICAL],
                match_keys=_record_match_keys(record),
            )
        )

    drafts.sort(key=lambda d: (d.type, d.title, d.txn_ids, d.record_ids))
    return tuple(drafts)


def _group_by_counterparty(rows: Sequence[BankTxn]) -> list[list[BankTxn]]:
    """PRD 6.3: group by counterparty when resolvable, otherwise one case per row."""
    grouped: dict[str, list[BankTxn]] = defaultdict(list)
    singles: list[list[BankTxn]] = []
    for txn in rows:
        if txn.counterparty_norm:
            grouped[txn.counterparty_norm].append(txn)
        else:
            singles.append([txn])
    ordered = [grouped[key] for key in sorted(grouped)]
    ordered.extend(sorted(singles, key=lambda group: group[0].id))
    return ordered


def _single_title(case_type: CaseType, txn: BankTxn) -> str:
    amount = format_minor(txn.amount_minor, txn.currency)
    if case_type is CaseType.AMBIGUOUS_MATCH:
        return f"Two records fit {amount} equally well"
    if case_type is CaseType.AMOUNT_MISMATCH:
        return f"Amount mismatch on {amount}"
    return f"Timing difference on {amount}"


def _single_summary(case_type: CaseType, txn: BankTxn, result: MatchingResult) -> str:
    candidates = result.candidates_by_txn.get(txn.id, ())
    if case_type is CaseType.AMBIGUOUS_MATCH and len(candidates) >= 2:
        return (
            f"Candidates {candidates[0].record_id} and {candidates[1].record_id} score "
            f"{candidates[0].score} and {candidates[1].score}. The gap is inside the "
            f"ambiguity guard, so this needs a human."
        )
    if case_type is CaseType.TIMING_DIFFERENCE:
        records = result.timing_candidates.get(txn.id, ())
        return (
            f"An exact amount and reference match exists ({', '.join(records)}) but falls "
            f"outside the date window, so it is a period-cutoff question."
        )
    if candidates:
        return (
            f"Best candidate {candidates[0].record_id} scores {candidates[0].score} but the "
            f"amounts do not agree."
        )
    return "No ledger record explains this line."


def _draft(
    case_type: CaseType,
    members: Sequence[BankTxn],
    value_at_risk: int,
    threshold: int,
    *,
    title: str,
    summary: str,
) -> CaseDraft:
    priority = assign_priority(case_type, value_at_risk, threshold)
    return CaseDraft(
        type=case_type,
        priority=priority,
        title=title,
        summary=summary,
        txn_ids=tuple(t.id for t in members),
        value_at_risk_minor=value_at_risk,
        due_hours=PRIORITY_DUE_HOURS[priority],
        match_keys=_txn_match_keys(members),
    )


def _txn_match_keys(members: Sequence[BankTxn]) -> tuple[tuple[str, str], ...]:
    """Denormalised keys the StandingCaseListener intersects against (PRD section 11)."""
    keys: dict[tuple[str, str], None] = {}
    for txn in members:
        keys.setdefault((str(MatchKeyType.AMOUNT), str(txn.amount_minor)), None)
        if txn.reference_norm:
            keys.setdefault((str(MatchKeyType.REF), txn.reference_norm), None)
        if txn.counterparty_norm:
            keys.setdefault((str(MatchKeyType.COUNTERPARTY), txn.counterparty_norm), None)
        for invoice in extract_invoices(txn.narration):
            keys.setdefault((str(MatchKeyType.INVOICE), invoice), None)
    return tuple(sorted(keys))


def _record_match_keys(record: PaymentRecord) -> tuple[tuple[str, str], ...]:
    keys: dict[tuple[str, str], None] = {
        (str(MatchKeyType.AMOUNT), str(record.amount_minor)): None
    }
    if record.reference_norm:
        keys.setdefault((str(MatchKeyType.REF), record.reference_norm), None)
    if record.counterparty_norm:
        keys.setdefault((str(MatchKeyType.COUNTERPARTY), record.counterparty_norm), None)
    return tuple(sorted(keys))
