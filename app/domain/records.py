from dataclasses import dataclass, field
from datetime import date, datetime

from app.domain.enums import CaseType, Direction, MatchMethod, MatchState, Priority

# Pure value objects. The deterministic engines operate on these alone, with no
# database or network access, so the determinism and property gates in PRD 20
# run without infrastructure.


@dataclass(frozen=True)
class BankTxn:
    id: str
    row_index: int
    value_date: date
    narration: str
    amount_minor: int
    direction: Direction
    currency: str = "NGN"
    reference_norm: str = ""
    counterparty_norm: str = ""
    balance_minor: int | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.amount_minor <= 0:
            raise ValueError(f"amount_minor must be positive, got {self.amount_minor}")


@dataclass(frozen=True)
class PaymentRecord:
    id: str
    record_date: date
    amount_minor: int
    direction: Direction
    currency: str = "NGN"
    reference_norm: str = ""
    counterparty_norm: str = ""
    external_id: str = ""

    def __post_init__(self) -> None:
        if self.amount_minor <= 0:
            raise ValueError(f"amount_minor must be positive, got {self.amount_minor}")


@dataclass(frozen=True)
class ScoreBreakdown:
    """Every component is surfaced in the UI, so the score is never a bare number."""

    amount: int = 0
    reference: int = 0
    date: int = 0
    counterparty: int = 0

    @property
    def total(self) -> int:
        return self.amount + self.reference + self.date + self.counterparty

    def as_dict(self) -> dict[str, int]:
        return {
            "amount": self.amount,
            "reference": self.reference,
            "date": self.date,
            "counterparty": self.counterparty,
            "total": self.total,
        }


@dataclass(frozen=True)
class Candidate:
    txn_id: str
    record_id: str
    breakdown: ScoreBreakdown
    method: MatchMethod

    @property
    def score(self) -> int:
        return self.breakdown.total


@dataclass(frozen=True)
class Match:
    txn_id: str
    record_id: str
    score: int
    method: MatchMethod
    state: MatchState
    breakdown: ScoreBreakdown


@dataclass(frozen=True)
class DuplicateGroup:
    key: tuple[int, date, str]
    txn_ids: tuple[str, ...]


@dataclass(frozen=True)
class MatchingResult:
    # Assigned pairs, in AUTO or REVIEW state. A REVIEW pair consumes both sides
    # until a human decides it, so it still blocks reconciliation completion.
    matches: tuple[Match, ...]
    unmatched_txn_ids: tuple[str, ...]
    unmatched_record_ids: tuple[str, ...]
    duplicate_groups: tuple[DuplicateGroup, ...]
    ambiguous_txn_ids: tuple[str, ...]
    # Every candidate considered, keyed by transaction, for the score-breakdown UI.
    candidates_by_txn: dict[str, tuple[Candidate, ...]] = field(default_factory=dict)
    # Exact amount+reference pairs that fall outside the date window. Feeds the
    # TIMING_DIFFERENCE typing rule, which is otherwise unreachable.
    timing_candidates: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def review_matches(self) -> tuple[Match, ...]:
        return tuple(m for m in self.matches if m.state is MatchState.REVIEW)

    @property
    def auto_matches(self) -> tuple[Match, ...]:
        return tuple(m for m in self.matches if m.state is MatchState.AUTO)


@dataclass(frozen=True)
class CaseDraft:
    """An exception case before it is persisted and bound to a Slack thread."""

    type: CaseType
    priority: Priority
    title: str
    summary: str
    txn_ids: tuple[str, ...]
    record_ids: tuple[str, ...] = ()
    value_at_risk_minor: int = 0
    due_hours: int = 24
    match_keys: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class EvidenceMessage:
    """An indexed workspace message, PRD 6.4."""

    id: str
    channel_id: str
    author_slack_id: str
    ts: str
    posted_at: datetime
    excerpt: str
    amounts_minor: tuple[int, ...] = ()
    refs_norm: tuple[str, ...] = ()
    invoices: tuple[str, ...] = ()
    counterparties: tuple[str, ...] = ()
    permalink: str = ""


@dataclass(frozen=True)
class ListenerHit:
    case_id: str
    evidence_id: str
    score: int
    matched_on: tuple[str, ...]
    notify: bool
    suppressed_reason: str = ""
