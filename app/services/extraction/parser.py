from dataclasses import dataclass, field
from typing import Sequence

from app.core.errors import BankReconError, ErrorCode
from app.domain.dates import DateInference, infer_date_format
from app.domain.enums import Direction, ExtractionMethod
from app.domain.money import AmountLocale, detect_currency, detect_locale, parse_amount
from app.domain.records import BankTxn
from app.domain.text import normalize_counterparty, normalize_reference
from app.services.extraction.columns import ColumnMap

# PRD 6.1 steps 5 to 7. Pure over a table of cells, so the golden fixture and the
# locale/date matrices run without touching a PDF.


@dataclass
class ExtractionResult:
    rows: list[BankTxn] = field(default_factory=list)
    method: ExtractionMethod = ExtractionMethod.TEXT_LAYER
    confidence: int = 0
    warnings: list[str] = field(default_factory=list)
    currency: str = "NGN"
    inferred_date_format: str = ""
    balance_breaks: int = 0
    skipped_rows: int = 0
    llm_column_assist_used: bool = False
    balance_break_row_ids: list[str] = field(default_factory=list)


def _cell(row: Sequence[str | None], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return (row[index] or "").strip()


def compute_confidence(
    *,
    ocr_used: bool,
    balance_breaks: int,
    skipped_rows: int,
    llm_column_assist_used: bool,
) -> int:
    """PRD 6.1 step 7. Deterministic, floored at 0."""
    score = (
        100
        - 20 * int(ocr_used)
        - 5 * balance_breaks
        - 2 * skipped_rows
        - 10 * int(llm_column_assist_used)
    )
    return max(0, score)


def parse_rows(
    rows: Sequence[Sequence[str | None]],
    column_map: ColumnMap,
    *,
    method: ExtractionMethod = ExtractionMethod.TEXT_LAYER,
    llm_column_assist_used: bool = False,
    row_id_prefix: str = "T",
) -> ExtractionResult:
    result = ExtractionResult(
        method=method, llm_column_assist_used=llm_column_assist_used
    )

    amount_cells = [
        _cell(r, column_map.debit) + " " + _cell(r, column_map.credit) for r in rows
    ]
    locale = detect_locale(amount_cells)
    if locale is AmountLocale.COMMA_DECIMAL:
        result.warnings.append("comma_decimal_locale")

    currencies = {
        c
        for cell in amount_cells + [_cell(r, column_map.balance) for r in rows]
        if (c := detect_currency(cell))
    }
    if len(currencies) > 1:
        raise BankReconError(ErrorCode.E_MIXED_CURRENCY, currencies=" and ".join(sorted(currencies)))
    result.currency = next(iter(currencies), "NGN")

    date_cells = [_cell(r, column_map.date) for r in rows]
    usable = [(i, d) for i, d in enumerate(date_cells) if d]
    if not usable:
        raise BankReconError(ErrorCode.E_EXTRACTION_UNREADABLE)
    inference: DateInference = infer_date_format([d for _, d in usable])
    result.inferred_date_format = inference.candidate.name
    if not inference.monotonic:
        result.warnings.append("dates_not_chronological")
    dates_by_row = {row_index: value for (row_index, _), value in zip(usable, inference.values)}

    for index, row in enumerate(rows):
        value_date = dates_by_row.get(index)
        if value_date is None:
            result.skipped_rows += 1
            result.warnings.append(f"row_{index}_unparseable_date")
            continue

        debit = parse_amount(_cell(row, column_map.debit), locale)
        credit = parse_amount(_cell(row, column_map.credit), locale)

        # PRD 6.1: exactly one of debit or credit per row, else warn and skip.
        populated = [v for v in (debit, credit) if v]
        if len(populated) != 1:
            result.skipped_rows += 1
            result.warnings.append(
                f"row_{index}_" + ("both_columns" if len(populated) > 1 else "no_amount")
            )
            continue

        # Direction comes from the column, never from the narration.
        direction = Direction.DEBIT if debit else Direction.CREDIT
        amount = debit if debit else credit

        narration = _cell(row, column_map.narration)
        reference_raw = _cell(row, column_map.reference) or narration
        result.rows.append(
            BankTxn(
                id=f"{row_id_prefix}{index:04d}",
                row_index=index,
                value_date=value_date,
                narration=narration,
                amount_minor=amount,
                direction=direction,
                currency=result.currency,
                reference_norm=normalize_reference(reference_raw)
                if column_map.reference is not None
                else _reference_from_narration(narration),
                counterparty_norm=normalize_counterparty(narration),
                balance_minor=parse_amount(_cell(row, column_map.balance), locale),
            )
        )

    breaks = check_balance_continuity(result.rows)
    result.balance_breaks = len(breaks)
    result.balance_break_row_ids = [txn_id for txn_id, _ in breaks]
    if breaks:
        result.warnings.append(f"balance_continuity_breaks={len(breaks)}")

    result.confidence = compute_confidence(
        ocr_used=method is ExtractionMethod.OCR,
        balance_breaks=result.balance_breaks,
        skipped_rows=result.skipped_rows,
        llm_column_assist_used=llm_column_assist_used,
    )
    return result


def _reference_from_narration(narration: str) -> str:
    from app.domain.text import extract_references

    references = extract_references(narration)
    return references[0] if references else ""


def check_balance_continuity(rows: Sequence[BankTxn]) -> list[tuple[str, int]]:
    """PRD 6.1 step 6: balance[n] == balance[n-1] + credit[n] - debit[n].

    Returns the row id and the signed discrepancy for each break. Any break blocks
    reconciliation completion, so a silent arithmetic error cannot close a period.
    """
    breaks: list[tuple[str, int]] = []
    previous: int | None = None
    for txn in rows:
        if txn.balance_minor is None:
            previous = None
            continue
        if previous is not None:
            delta = txn.amount_minor if txn.direction is Direction.CREDIT else -txn.amount_minor
            expected = previous + delta
            if expected != txn.balance_minor:
                breaks.append((txn.id, txn.balance_minor - expected))
        previous = txn.balance_minor
    return breaks
