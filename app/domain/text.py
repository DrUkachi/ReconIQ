import re

# PRD 6.3: checked-in constant, not configuration. Order is irrelevant; membership is.
FEE_PATTERNS: tuple[str, ...] = (
    "COMMISSION",
    "CHARGE",
    "VAT",
    "STAMP DUTY",
    "SMS ALERT",
    "MAINTENANCE FEE",
    "NIP FEE",
    "E-LEVY",
)

# Channel and rail prefixes Nigerian banks stamp onto narrations. Stripped before
# counterparty extraction so "NIP/TRF FROM ADEOLA FARMS" resolves to "ADEOLA FARMS".
_NARRATION_NOISE: tuple[str, ...] = (
    "NIP",
    "NEFT",
    "RTGS",
    "USSD",
    "WEB",
    "POS",
    "ATM",
    "MOBILE",
    "TRANSFER",
    "TRF",
    "PAYMENT",
    "PMT",
    "FROM",
    "TO",
    "REF",
    "VIA",
    "INWARD",
    "OUTWARD",
    "CREDIT",
    "DEBIT",
)

# Legal-form suffixes carry no identity signal and hurt fuzzy comparison.
_LEGAL_SUFFIXES: tuple[str, ...] = (
    "LTD",
    "LIMITED",
    "PLC",
    "INC",
    "LLC",
    "NIG",
    "NIGERIA",
    "ENTERPRISES",
    "ENTERPRISE",
    "VENTURES",
    "GLOBAL",
    "SERVICES",
    "COMPANY",
    "CO",
    "AND SONS",
    "& SONS",
)

_NON_ALNUM = re.compile(r"[^A-Z0-9]+")
_WHITESPACE = re.compile(r"\s+")
_REFERENCE_TOKEN = re.compile(r"\b[A-Z0-9]{6,}\b")
_HAS_DIGIT = re.compile(r"\d")
_HAS_ALPHA = re.compile(r"[A-Z]")
_INVOICE = re.compile(r"\bINV[-/ ]?(\d+)\b", re.IGNORECASE)


def normalize_reference(raw: str | None) -> str:
    """Uppercase alphanumerics only. Empty string means 'no usable reference'."""
    if not raw:
        return ""
    return _NON_ALNUM.sub("", str(raw).upper())


def is_reference_like(token: str) -> bool:
    """PRD 6.4: 6+ chars, at least one digit and one letter."""
    upper = token.upper()
    return len(upper) >= 6 and bool(_HAS_DIGIT.search(upper)) and bool(_HAS_ALPHA.search(upper))


def extract_references(text: str) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for token in _REFERENCE_TOKEN.findall(str(text).upper()):
        if is_reference_like(token):
            seen.setdefault(token, None)
    return tuple(seen)


def extract_invoices(text: str) -> tuple[str, ...]:
    """Normalised to INV-<digits> (PRD 6.4)."""
    seen: dict[str, None] = {}
    for digits in _INVOICE.findall(str(text)):
        seen.setdefault(f"INV-{digits.lstrip('0') or '0'}", None)
    return tuple(seen)


def normalize_counterparty(raw: str | None) -> str:
    """Reduce a narration or payee field to a comparable party name.

    Low precision is acceptable: this feeds a similarity score and a recall aid,
    never a matching decision on its own.
    """
    if not raw:
        return ""
    text = _NON_ALNUM.sub(" ", str(raw).upper())
    tokens = [t for t in _WHITESPACE.split(text) if t]

    # Drop rail/channel noise and anything that is purely a number or a reference code.
    tokens = [
        t
        for t in tokens
        if t not in _NARRATION_NOISE and not t.isdigit() and not is_reference_like(t)
    ]

    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    tokens = [t for t in tokens if t not in _LEGAL_SUFFIXES]

    return " ".join(tokens).strip()


def is_fee_narration(narration: str | None) -> bool:
    """PRD 6.3 rule 6: debit narration matching the checked-in fee pattern list."""
    if not narration:
        return False
    upper = str(narration).upper()
    return any(pattern in upper for pattern in FEE_PATTERNS)


def mask_account(account_number: str | None) -> str:
    """PRD section 22: only the last four are ever persisted."""
    if not account_number:
        return ""
    digits = re.sub(r"\D", "", str(account_number))
    return digits[-4:] if len(digits) >= 4 else digits
