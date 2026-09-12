from collections import defaultdict
from typing import Sequence

from app.domain.enums import MatchMethod, MatchState
from app.domain.records import (
    BankTxn,
    Candidate,
    DuplicateGroup,
    Match,
    MatchingResult,
    PaymentRecord,
)
from app.services.matching.scoring import (
    MatchingConfig,
    amounts_within_tolerance,
    score_pair,
)

# PRD 6.2. Fully deterministic, zero LLM calls, no I/O. Every ordering decision is
# made explicit so that running this 100 times produces byte-identical output.


def detect_duplicates(txns: Sequence[BankTxn]) -> tuple[DuplicateGroup, ...]:
    """Pass 0. Group by (amount, value_date, reference) where the reference is usable.

    Rows without a reference are never grouped: two genuine ₦5,000 transfers on the
    same day would otherwise be reported as a duplicate.
    """
    buckets: dict[tuple[int, object, str], list[str]] = defaultdict(list)
    for txn in txns:
        if not txn.reference_norm:
            continue
        buckets[(txn.amount_minor, txn.value_date, txn.reference_norm)].append(txn.id)

    groups = [
        DuplicateGroup(key=key, txn_ids=tuple(sorted(ids)))
        for key, ids in buckets.items()
        if len(ids) > 1
    ]
    groups.sort(key=lambda g: (g.key[0], g.key[1], g.key[2]))
    return tuple(groups)


def _is_exact(txn: BankTxn, record: PaymentRecord) -> bool:
    """PRD 6.2 pass 1 predicate, with the date window applied.

    The window is not in the spec's pass-1 sentence, but without it no pair can
    ever reach the TIMING_DIFFERENCE typing rule (6.3 rule 5), which exists
    precisely for an exact match sitting outside the window. Windowing here is
    also the financially correct reading: a payment booked in March that clears
    in April is a period-cutoff question for a human, not an auto-match.
    """
    if txn.direction is not record.direction:
        return False
    if txn.currency != record.currency:
        return False
    if txn.amount_minor != record.amount_minor:
        return False
    if txn.reference_norm and txn.reference_norm == record.reference_norm:
        return True
    return (
        txn.value_date == record.record_date
        and bool(txn.counterparty_norm)
        and txn.counterparty_norm == record.counterparty_norm
    )


def _exact_outside_window(
    txn: BankTxn, record: PaymentRecord, window_days: int
) -> bool:
    if txn.direction is not record.direction or txn.currency != record.currency:
        return False
    if txn.amount_minor != record.amount_minor:
        return False
    if not txn.reference_norm or txn.reference_norm != record.reference_norm:
        return False
    return abs((txn.value_date - record.record_date).days) > window_days


def run_matching(
    txns: Sequence[BankTxn],
    records: Sequence[PaymentRecord],
    config: MatchingConfig | None = None,
) -> MatchingResult:
    config = config or MatchingConfig()

    txn_by_id = {t.id: t for t in txns}
    record_by_id = {r.id: r for r in records}

    duplicate_groups = detect_duplicates(txns)
    duplicated = {tid for group in duplicate_groups for tid in group.txn_ids}

    eligible = sorted((t for t in txns if t.id not in duplicated), key=lambda t: t.id)
    ordered_records = sorted(records, key=lambda r: r.id)

    candidates_by_txn: dict[str, tuple[Candidate, ...]] = {}
    timing_candidates: dict[str, tuple[str, ...]] = {}

    for txn in eligible:
        scored: list[Candidate] = []
        timing: list[str] = []
        for record in ordered_records:
            if _exact_outside_window(txn, record, config.date_window_days):
                timing.append(record.id)
            if txn.direction is not record.direction:
                continue
            if txn.currency != record.currency:
                continue
            if not amounts_within_tolerance(
                txn.amount_minor, record.amount_minor, config.amount_tolerance_bps
            ):
                continue
            if abs((txn.value_date - record.record_date).days) > config.date_window_days:
                continue

            method = MatchMethod.EXACT if _is_exact(txn, record) else MatchMethod.SCORED
            breakdown = score_pair(
                txn_amount=txn.amount_minor,
                record_amount=record.amount_minor,
                txn_ref=txn.reference_norm,
                record_ref=record.reference_norm,
                txn_date=txn.value_date,
                record_date=record.record_date,
                txn_counterparty=txn.counterparty_norm,
                record_counterparty=record.counterparty_norm,
                tolerance_bps=config.amount_tolerance_bps,
            )
            scored.append(Candidate(txn.id, record.id, breakdown, method))

        scored.sort(
            key=lambda c: (
                -c.score,
                record_by_id[c.record_id].record_date,
                c.record_id,
                c.txn_id,
            )
        )
        candidates_by_txn[txn.id] = tuple(scored)
        if timing:
            timing_candidates[txn.id] = tuple(sorted(timing))

    ambiguous = _find_ambiguous(candidates_by_txn, config)

    assignable = [
        candidate
        for txn_id, candidates in candidates_by_txn.items()
        if txn_id not in ambiguous
        for candidate in candidates
        if candidate.score >= config.review_floor
    ]
    # PRD 6.2 stability rule. A documented greedy approximation, not a bipartite optimum.
    assignable.sort(
        key=lambda c: (
            -c.score,
            record_by_id[c.record_id].record_date,
            c.record_id,
            c.txn_id,
        )
    )

    matches: list[Match] = []
    taken_txns: set[str] = set()
    taken_records: set[str] = set()
    for candidate in assignable:
        if candidate.txn_id in taken_txns or candidate.record_id in taken_records:
            continue
        taken_txns.add(candidate.txn_id)
        taken_records.add(candidate.record_id)
        state = (
            MatchState.AUTO
            if candidate.score >= config.auto_match_threshold
            else MatchState.REVIEW
        )
        matches.append(
            Match(
                txn_id=candidate.txn_id,
                record_id=candidate.record_id,
                score=candidate.score,
                method=candidate.method,
                state=state,
                breakdown=candidate.breakdown,
            )
        )

    matches.sort(key=lambda m: (m.txn_id, m.record_id))

    unmatched_txns = tuple(
        sorted(
            t.id
            for t in txns
            if t.id not in taken_txns and t.id not in duplicated and t.id not in ambiguous
        )
    )
    unmatched_records = tuple(sorted(r.id for r in records if r.id not in taken_records))

    return MatchingResult(
        matches=tuple(matches),
        unmatched_txn_ids=unmatched_txns,
        unmatched_record_ids=unmatched_records,
        duplicate_groups=duplicate_groups,
        ambiguous_txn_ids=tuple(sorted(ambiguous)),
        candidates_by_txn=candidates_by_txn,
        timing_candidates=timing_candidates,
    )


def _find_ambiguous(
    candidates_by_txn: dict[str, tuple[Candidate, ...]], config: MatchingConfig
) -> set[str]:
    """PRD 6.2 ambiguity guard: a near-tie is never resolved by the machine.

    Only applies when the leader is credible (at or above the review floor);
    two equally bad candidates are simply an unmatched row, not an ambiguity.
    """
    ambiguous: set[str] = set()
    for txn_id, candidates in candidates_by_txn.items():
        if len(candidates) < 2:
            continue
        top, second = candidates[0], candidates[1]
        if top.score < config.review_floor:
            continue
        if top.score - second.score < config.ambiguity_gap:
            ambiguous.add(txn_id)
    return ambiguous
