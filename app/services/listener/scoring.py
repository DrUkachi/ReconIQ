from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Sequence

from app.domain.enums import MatchKeyType
from app.domain.records import EvidenceMessage

# PRD 6.5. The listener is regex- and set-driven, never model-driven: a hostile
# message can become evidence but can never cause an action (threat model, section 16).

REFERENCE_POINTS = 60
INVOICE_POINTS = 55
AMOUNT_POINTS = 35
COUNTERPARTY_POINTS = 20
ASSIGNEE_POINTS = 10

COUNTERPARTY_FLOOR = 0.75


@dataclass(frozen=True)
class ListenerConfig:
    threshold: int = 55
    per_case_cooldown_hours: int = 6
    max_per_case: int = 3
    max_per_workspace_hour: int = 10


@dataclass(frozen=True)
class CaseKeys:
    """Denormalised match keys for one open case (the case_match_key table)."""

    case_id: str
    created_at: datetime
    amounts_minor: frozenset[int] = frozenset()
    refs_norm: frozenset[str] = frozenset()
    invoices: frozenset[str] = frozenset()
    counterparties: frozenset[str] = frozenset()
    assignee_slack_id: str | None = None

    @classmethod
    def from_pairs(
        cls,
        case_id: str,
        created_at: datetime,
        pairs: Iterable[tuple[str, str]],
        assignee_slack_id: str | None = None,
    ) -> "CaseKeys":
        amounts: set[int] = set()
        refs: set[str] = set()
        invoices: set[str] = set()
        counterparties: set[str] = set()
        for key_type, value in pairs:
            if key_type == MatchKeyType.AMOUNT:
                amounts.add(int(value))
            elif key_type == MatchKeyType.REF:
                refs.add(value)
            elif key_type == MatchKeyType.INVOICE:
                invoices.add(value)
            elif key_type == MatchKeyType.COUNTERPARTY:
                counterparties.add(value)
        return cls(
            case_id=case_id,
            created_at=created_at,
            amounts_minor=frozenset(amounts),
            refs_norm=frozenset(refs),
            invoices=frozenset(invoices),
            counterparties=frozenset(counterparties),
            assignee_slack_id=assignee_slack_id,
        )


@dataclass(frozen=True)
class ListenerScore:
    case_id: str
    score: int
    matched_on: tuple[str, ...]
    matched_keys: tuple[tuple[str, str], ...]


def trigram_similarity(a: str, b: str) -> float:
    """pg_trgm-compatible similarity, so app-side scoring and a future GIN index agree.

    Postgres pads with two leading spaces and one trailing space, then compares
    trigram sets by Jaccard index.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    set_a, set_b = _trigrams(a), _trigrams(b)
    if not set_a or not set_b:
        return 0.0
    union = set_a | set_b
    return len(set_a & set_b) / len(union) if union else 0.0


def _trigrams(value: str) -> frozenset[str]:
    words = [w for w in value.lower().split() if w]
    grams: set[str] = set()
    for word in words:
        padded = f"  {word} "
        for i in range(len(padded) - 2):
            grams.add(padded[i : i + 3])
    return frozenset(grams)


def score_message(
    case: CaseKeys, message: EvidenceMessage, config: ListenerConfig | None = None
) -> ListenerScore | None:
    """Score one indexed message against one open case.

    Returns None when the message predates the case: a case cannot be answered by
    a message written before the question existed (PRD 6.5, required signal).
    """
    config = config or ListenerConfig()
    if message.posted_at <= case.created_at:
        return None

    score = 0
    matched_on: list[str] = []
    matched_keys: list[tuple[str, str]] = []

    shared_refs = sorted(set(message.refs_norm) & case.refs_norm)
    if shared_refs:
        score += REFERENCE_POINTS
        matched_on.append(f"reference {shared_refs[0]}")
        matched_keys.extend((str(MatchKeyType.REF), r) for r in shared_refs)

    shared_invoices = sorted(set(message.invoices) & case.invoices)
    if shared_invoices:
        score += INVOICE_POINTS
        matched_on.append(f"invoice {shared_invoices[0]}")
        matched_keys.extend((str(MatchKeyType.INVOICE), i) for i in shared_invoices)

    shared_amounts = sorted(set(message.amounts_minor) & case.amounts_minor)
    if shared_amounts:
        score += AMOUNT_POINTS
        matched_on.append(f"amount {shared_amounts[0]}")
        matched_keys.extend((str(MatchKeyType.AMOUNT), str(a)) for a in shared_amounts)

    best_cp = _best_counterparty(message.counterparties, case.counterparties)
    if best_cp is not None:
        score += COUNTERPARTY_POINTS
        matched_on.append(f"counterparty {best_cp}")
        matched_keys.append((str(MatchKeyType.COUNTERPARTY), best_cp))

    if case.assignee_slack_id and message.author_slack_id == case.assignee_slack_id:
        score += ASSIGNEE_POINTS
        matched_on.append("author is the case assignee")

    if score == 0:
        return None

    return ListenerScore(
        case_id=case.case_id,
        score=score,
        matched_on=tuple(matched_on),
        matched_keys=tuple(matched_keys),
    )


def _best_counterparty(
    message_parties: Sequence[str], case_parties: frozenset[str]
) -> str | None:
    best: tuple[float, str] | None = None
    for candidate in message_parties:
        for known in case_parties:
            ratio = trigram_similarity(candidate, known)
            if ratio >= COUNTERPARTY_FLOOR and (best is None or ratio > best[0]):
                best = (ratio, known)
    return best[1] if best else None


@dataclass(frozen=True)
class NotifyDecision:
    notify: bool
    reason: str = ""


def decide_notification(
    *,
    score: int,
    notifications_for_case: int,
    last_notified_at: datetime | None,
    workspace_notifications_last_hour: int,
    suppressed: bool,
    now: datetime,
    config: ListenerConfig | None = None,
) -> NotifyDecision:
    """PRD 6.5 step 5. Every limit stores the evidence silently rather than dropping it.

    Order matters for the audit trail: the reason recorded is the first limit hit.
    """
    config = config or ListenerConfig()
    if suppressed:
        return NotifyDecision(False, "suppressed_by_not_related")
    if score < config.threshold:
        return NotifyDecision(False, "below_threshold")
    if notifications_for_case >= config.max_per_case:
        return NotifyDecision(False, "case_notification_cap")
    if last_notified_at is not None:
        cooldown = timedelta(hours=config.per_case_cooldown_hours)
        if now - last_notified_at < cooldown:
            return NotifyDecision(False, "case_cooldown")
    if workspace_notifications_last_hour >= config.max_per_workspace_hour:
        return NotifyDecision(False, "workspace_hourly_cap")
    return NotifyDecision(True)
