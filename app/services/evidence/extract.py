import re
from decimal import Decimal, ROUND_HALF_UP

from app.domain.money import MINOR_UNITS_PER_MAJOR
from app.domain.text import extract_invoices, extract_references, normalize_counterparty

# PRD 6.4. Pure regex, no LLM. Retrieval must never depend on a model (rule E1).

# Checked-in verb list. A bare number only becomes an amount when it sits next to one.
PAYMENT_VERBS: tuple[str, ...] = (
    "PAID",
    "PAY",
    "PAYING",
    "SENT",
    "SEND",
    "SENDING",
    "TRANSFERRED",
    "TRANSFER",
    "SETTLED",
    "SETTLE",
    "REMITTED",
    "CLEARED",
    "DEPOSITED",
    "REFUNDED",
    "INVOICED",
    "CHARGED",
    "RECEIVED",
    "OWED",
    "OWE",
)

_CURRENCY_AMOUNT = re.compile(
    r"(?:₦|NGN|N)\s?([\d,]+(?:\.\d{2})?)(k|m)?\b",
    re.IGNORECASE,
)
# Bare numbers are only harvested near a payment verb, per 6.4.
_BARE_AMOUNT = re.compile(r"\b([\d,]{4,}(?:\.\d{2})?|\d+(?:\.\d+)?)(k|m)\b|\b([\d,]{4,}(?:\.\d{2})?)\b")

_VERB_WINDOW = 40

# A capitalised span of 2 to 4 tokens, used as a recall aid only.
_PROPER_SPAN = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b")

_MULTIPLIERS: dict[str, int] = {"k": 1_000, "m": 1_000_000}

MIN_INDEXABLE_LENGTH = 8


def _to_minor(digits: str, suffix: str | None) -> int | None:
    cleaned = digits.replace(",", "").strip()
    if not cleaned:
        return None
    try:
        value = Decimal(cleaned)
    except Exception:
        return None
    if suffix:
        value *= _MULTIPLIERS[suffix.lower()]
    minor = (value * MINOR_UNITS_PER_MAJOR).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(minor) if minor > 0 else None


def _near_payment_verb(text: str, start: int) -> bool:
    window = text[max(0, start - _VERB_WINDOW) : start + _VERB_WINDOW].upper()
    return any(verb in window for verb in PAYMENT_VERBS)


def extract_amounts(text: str) -> tuple[int, ...]:
    """Currency-marked amounts always; bare numbers only beside a payment verb.

    The k/m suffix is not in the PRD's regex but is required for the demo beat
    ("sent the 85k" must match an ₦85,000 case) and is how people actually write
    amounts in chat.
    """
    found: dict[int, None] = {}
    consumed: list[tuple[int, int]] = []

    for match in _CURRENCY_AMOUNT.finditer(text):
        minor = _to_minor(match.group(1), match.group(2))
        if minor is not None:
            found.setdefault(minor, None)
            consumed.append(match.span())

    for match in _BARE_AMOUNT.finditer(text):
        if any(start <= match.start() < end for start, end in consumed):
            continue
        if not _near_payment_verb(text, match.start()):
            continue
        digits = match.group(1) or match.group(3)
        suffix = match.group(2)
        if digits is None:
            continue
        minor = _to_minor(digits, suffix)
        if minor is not None:
            found.setdefault(minor, None)

    return tuple(sorted(found))


def extract_counterparties(text: str) -> tuple[str, ...]:
    found: dict[str, None] = {}
    for span in _PROPER_SPAN.findall(text):
        normalised = normalize_counterparty(span)
        if normalised and len(normalised) >= 4:
            found.setdefault(normalised, None)
    return tuple(sorted(found))


def is_indexable(text: str, *, is_bot: bool = False) -> bool:
    """PRD 6.4: skip bot messages and anything under 8 characters."""
    if is_bot:
        return False
    return len(text.strip()) >= MIN_INDEXABLE_LENGTH


def extract_signals(text: str) -> dict[str, tuple]:
    """All four signal families for one message, ready to persist on the index row."""
    return {
        "amounts_minor": extract_amounts(text),
        "refs_norm": extract_references(text),
        "invoices": extract_invoices(text),
        "counterparties": extract_counterparties(text),
    }


def excerpt(text: str, limit: int = 200) -> str:
    """PRD section 22: only a 200 character excerpt is ever stored."""
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed[:limit]
