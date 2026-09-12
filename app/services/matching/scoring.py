import math
from dataclasses import dataclass
from datetime import date

from rapidfuzz import fuzz

from app.domain.records import ScoreBreakdown

# PRD 6.2 scoring table. These are the only weights in the system; changing one
# changes the golden fixture, which is the point.
AMOUNT_EXACT = 40
AMOUNT_TOLERANCE = 25
REFERENCE_EXACT = 30
REFERENCE_FUZZY = 20
DATE_EXACT = 15
DATE_WITHIN_1 = 12
DATE_WITHIN_3 = 8
COUNTERPARTY_MAX = 15

REFERENCE_FUZZY_FLOOR = 0.85


@dataclass(frozen=True)
class MatchingConfig:
    auto_match_threshold: int = 90
    review_floor: int = 60
    ambiguity_gap: int = 5
    date_window_days: int = 5
    amount_tolerance_bps: int = 0


def _round_half_up(value: float) -> int:
    """Explicit half-up. Python's round() is banker's rounding, which would make
    the fixture depend on a rule nobody reading the PRD would expect."""
    return math.floor(value + 0.5)


def amounts_within_tolerance(a: int, b: int, tolerance_bps: int) -> bool:
    if a == b:
        return True
    if tolerance_bps <= 0:
        return False
    return abs(a - b) * 10_000 <= a * tolerance_bps


def amount_component(txn_amount: int, record_amount: int, tolerance_bps: int) -> int:
    if txn_amount == record_amount:
        return AMOUNT_EXACT
    if amounts_within_tolerance(txn_amount, record_amount, tolerance_bps):
        return AMOUNT_TOLERANCE
    return 0


def reference_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return fuzz.ratio(a, b) / 100.0


def reference_component(txn_ref: str, record_ref: str) -> int:
    if not txn_ref or not record_ref:
        return 0
    if txn_ref == record_ref:
        return REFERENCE_EXACT
    if txn_ref in record_ref or record_ref in txn_ref:
        return REFERENCE_FUZZY
    if reference_similarity(txn_ref, record_ref) >= REFERENCE_FUZZY_FLOOR:
        return REFERENCE_FUZZY
    return 0


def date_component(txn_date: date, record_date: date) -> int:
    delta = abs((txn_date - record_date).days)
    if delta == 0:
        return DATE_EXACT
    if delta <= 1:
        return DATE_WITHIN_1
    if delta <= 3:
        return DATE_WITHIN_3
    return 0


def counterparty_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return fuzz.ratio(a, b) / 100.0


def counterparty_component(txn_cp: str, record_cp: str) -> int:
    ratio = counterparty_similarity(txn_cp, record_cp)
    if ratio <= 0.0:
        return 0
    return min(COUNTERPARTY_MAX, _round_half_up(ratio * COUNTERPARTY_MAX))


def score_pair(
    *,
    txn_amount: int,
    record_amount: int,
    txn_ref: str,
    record_ref: str,
    txn_date: date,
    record_date: date,
    txn_counterparty: str,
    record_counterparty: str,
    tolerance_bps: int,
) -> ScoreBreakdown:
    return ScoreBreakdown(
        amount=amount_component(txn_amount, record_amount, tolerance_bps),
        reference=reference_component(txn_ref, record_ref),
        date=date_component(txn_date, record_date),
        counterparty=counterparty_component(txn_counterparty, record_counterparty),
    )
