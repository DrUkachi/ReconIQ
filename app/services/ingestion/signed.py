"""Pure adapter for an explicitly signed cash-account export, not journal debits.

The legacy statement parser still derives direction from debit/credit columns.
This separate profile uses the supplied export's positive=inflow convention.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.core.errors import BankReconError, ErrorCode
from app.domain.enums import Direction
from app.domain.records import BankTxn, PaymentRecord
from app.domain.text import normalize_counterparty, normalize_reference

HEADERS = (
    "Transaction Date", "Transaction Reference", "Amount", "Currency", "Transaction Text",
)
SUPPORTED_CURRENCIES = frozenset({"NGN", "USD", "EUR"})
_AMOUNT = re.compile(r"-?[0-9]+\.[0-9]{2}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


@dataclass(frozen=True)
class SourceRow:
    source_file: str
    sha256: str
    index: int
    page: int | None
    page_row: int
    raw: tuple[str | None, ...]

    @property
    def id(self) -> str:
        # Physical duplicates survive; rereading identical bytes has stable IDs.
        return f"{self.sha256}:{self.index}"


@dataclass(frozen=True)
class ParsedRow:
    source: SourceRow
    transaction_date: date
    signed_minor: int
    currency: str
    reference: str | None
    narration: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class RejectedRow:
    source: SourceRow
    reasons: tuple[str, ...]
    code: ErrorCode = ErrorCode.E_VALIDATION


@dataclass(frozen=True)
class ImportResult:
    accepted: tuple[ParsedRow, ...]
    rejected: tuple[RejectedRow, ...]
    byte_size: int = 0


def parse_signed_rows(
    rows: list[SourceRow], *, currencies: frozenset[str] = SUPPORTED_CURRENCIES,
) -> ImportResult:
    accepted, rejected = [], []
    for source in rows:
        if len(source.raw) != len(HEADERS):
            rejected.append(RejectedRow(source, ("expected_five_fields",)))
            continue
        raw_date, reference, amount, raw_currency, narration = (
            (cell or "").strip() for cell in source.raw
        )
        reasons, warnings = [], []
        parsed_date = None
        try:
            if not _DATE.fullmatch(raw_date):
                raise ValueError
            parsed_date = date.fromisoformat(raw_date)
        except ValueError:
            reasons.append("invalid_iso_date")
        minor = None
        if not _AMOUNT.fullmatch(amount):
            reasons.append("invalid_decimal_amount")
        elif len(amount.lstrip("-").split(".")[0]) > 18:
            reasons.append("amount_out_of_range")
        else:
            minor = int(Decimal(amount) * 100)
            if abs(minor) > 2**63 - 1:
                reasons.append("amount_out_of_range")
        currency = raw_currency.upper()
        if currency not in currencies:
            reasons.append("unsupported_or_missing_currency")
        if reasons:
            rejected.append(RejectedRow(source, tuple(reasons)))
            continue
        if currency != raw_currency:
            warnings.append("currency_normalized")
        if not reference:
            warnings.append("missing_reference")
        if not narration:
            warnings.append("missing_narration")
        if minor == 0:
            warnings.append("zero_value_excluded_from_matching")
        accepted.append(ParsedRow(
            source, parsed_date, minor, currency, reference or None,
            narration or None, tuple(warnings),
        ))
    return ImportResult(tuple(accepted), tuple(rejected))


@dataclass(frozen=True)
class MatchingInputs:
    bank_by_currency: dict[str, tuple[BankTxn, ...]]
    ledger_by_currency: dict[str, tuple[PaymentRecord, ...]]
    excluded: tuple[ParsedRow, ...]


def prepare_matching_inputs(
    bank: ImportResult, ledger: ImportResult, start: date, end: date,
) -> MatchingInputs:
    """Apply the cutoff before matching and never silently use a partial import."""
    if start > end:
        raise BankReconError(ErrorCode.E_VALIDATION, detail="The period start is after its end.")
    if bank.rejected or ledger.rejected:
        raise BankReconError(
            ErrorCode.E_VALIDATION,
            detail="Resolve rejected source rows before preparing matching inputs.",
        )
    banks, ledgers, excluded = {}, {}, []
    for kind, imported, groups in (("bank", bank, banks), ("ledger", ledger, ledgers)):
        for row in imported.accepted:
            if not start <= row.transaction_date <= end or row.signed_minor == 0:
                excluded.append(row)
                continue
            fields = dict(
                id=f"{kind}:{row.source.id}", amount_minor=abs(row.signed_minor),
                direction=Direction.CREDIT if row.signed_minor > 0 else Direction.DEBIT,
                currency=row.currency,
                reference_norm=normalize_reference(row.reference or ""),
                counterparty_norm=normalize_counterparty(row.narration or ""),
            )
            if kind == "bank":
                record = BankTxn(
                    **fields, row_index=row.source.index - 1,
                    value_date=row.transaction_date, narration=row.narration or "",
                    warnings=row.warnings,
                )
            else:
                record = PaymentRecord(
                    **fields, record_date=row.transaction_date, external_id=row.source.id,
                )
            groups.setdefault(row.currency, []).append(record)
    return MatchingInputs(
        {c: tuple(v) for c, v in sorted(banks.items())},
        {c: tuple(v) for c, v in sorted(ledgers.items())}, tuple(excluded),
    )
