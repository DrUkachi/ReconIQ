import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import StrEnum
from typing import Iterable

# PRD hard constraint: integer minor units end to end, no floats.
MINOR_UNITS_PER_MAJOR = 100

CURRENCY_SYMBOLS: dict[str, str] = {
    "₦": "NGN",
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
}

CURRENCY_CODES: frozenset[str] = frozenset({"NGN", "USD", "EUR", "GBP", "GHS", "KES", "ZAR"})

_CURRENCY_TOKEN_RE = re.compile(
    r"(?:^|[\s(])(" + "|".join(sorted(CURRENCY_CODES, key=len, reverse=True)) + r")(?:$|[\s)\d])",
    re.IGNORECASE,
)

# A number written with dot thousands separators and a comma decimal: 1.234.567,89
_COMMA_DECIMAL_RE = re.compile(r"\d{1,3}(?:\.\d{3})+,\d{2}")

# Trailing or leading debit/credit markers some Nigerian banks emit.
_DR_CR_RE = re.compile(r"\b(?:DR|CR)\b\.?", re.IGNORECASE)

_NEGATIVE_RE = re.compile(r"^\s*[-(]|[-)]\s*$")


class AmountLocale(StrEnum):
    """Decimal convention, decided once per file and never per row (PRD 6.1)."""

    DOT_DECIMAL = "DOT_DECIMAL"  # 1,234,567.89
    COMMA_DECIMAL = "COMMA_DECIMAL"  # 1.234.567,89


def detect_locale(raw_amounts: Iterable[str]) -> AmountLocale:
    """PRD 6.1: if any amount matches the comma-decimal shape, the whole file is comma-decimal."""
    for raw in raw_amounts:
        if raw and _COMMA_DECIMAL_RE.search(raw):
            return AmountLocale.COMMA_DECIMAL
    return AmountLocale.DOT_DECIMAL


def strip_currency(raw: str) -> str:
    out = raw
    for symbol in CURRENCY_SYMBOLS:
        out = out.replace(symbol, " ")
    out = _CURRENCY_TOKEN_RE.sub(" ", out)
    out = _DR_CR_RE.sub(" ", out)
    return out


def looks_negative(raw: str) -> bool:
    return bool(_NEGATIVE_RE.search(raw.strip()))


def parse_amount(raw: str | None, locale: AmountLocale) -> int | None:
    """Parse a statement amount into positive minor units, or None if unparseable.

    Sign is discarded: direction comes from the debit/credit column, never from
    the amount or the narration (PRD 6.1 invariant).
    """
    if raw is None:
        return None
    text = strip_currency(str(raw)).strip()
    if not text:
        return None

    text = text.replace("(", "").replace(")", "").replace(" ", " ")
    text = re.sub(r"[\s_]", "", text)
    text = text.lstrip("+-").rstrip("+-")
    if not text:
        return None

    if locale is AmountLocale.COMMA_DECIMAL:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")

    if not re.fullmatch(r"\d*\.?\d*", text) or text in {"", "."}:
        return None

    try:
        value = Decimal(text)
    except InvalidOperation:
        return None

    minor = (value * MINOR_UNITS_PER_MAJOR).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(minor)


def detect_currency(raw: str) -> str | None:
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in raw:
            return code
    match = _CURRENCY_TOKEN_RE.search(raw)
    if match:
        return match.group(1).upper()
    return None


def format_minor(minor: int, currency: str = "NGN") -> str:
    """Render minor units for display. Never used as a parsing round-trip."""
    symbol = next((s for s, c in CURRENCY_SYMBOLS.items() if c == currency), "")
    major = Decimal(minor) / MINOR_UNITS_PER_MAJOR
    rendered = f"{major:,.2f}"
    return f"{symbol}{rendered}" if symbol else f"{currency} {rendered}"
