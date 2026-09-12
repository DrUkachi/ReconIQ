import re
from dataclasses import dataclass
from typing import Sequence

from app.domain.dates import CANDIDATES, parse_with
from app.domain.money import AmountLocale, parse_amount

# PRD 6.1 step 4: header text match first, then content heuristics. The LLM column
# assist (call site L1) is only reached when both fail.

HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "date": ("value date", "trans date", "transaction date", "posting date", "date", "day"),
    "narration": (
        "narration",
        "description",
        "particulars",
        "details",
        "remarks",
        "transaction details",
    ),
    "reference": ("reference", "ref no", "ref", "cheque", "instrument", "transaction id"),
    "debit": ("debit", "withdrawal", "withdrawals", "money out", "dr", "outflow"),
    "credit": ("credit", "lodgement", "lodgment", "deposit", "money in", "cr", "inflow"),
    "balance": ("balance", "running balance", "closing balance", "bal"),
}

_NUMERIC = re.compile(r"^[\s(₦$€£]*[\d.,]+[\s)]*(?:cr|dr)?\.?$", re.IGNORECASE)


@dataclass(frozen=True)
class ColumnMap:
    date: int
    narration: int
    reference: int | None = None
    debit: int | None = None
    credit: int | None = None
    balance: int | None = None
    # How the map was decided, which feeds the confidence score.
    source: str = "header"

    def as_dict(self) -> dict[str, int | None]:
        return {
            "date_col": self.date,
            "narration_col": self.narration,
            "ref_col": self.reference,
            "debit_col": self.debit,
            "credit_col": self.credit,
            "balance_col": self.balance,
        }


def _normalise_header(cell: str | None) -> str:
    return re.sub(r"\s+", " ", (cell or "").strip().lower())


def map_from_headers(header: Sequence[str | None]) -> ColumnMap | None:
    """Exact-then-substring match, longest synonym first so 'value date' beats 'date'."""
    normalised = [_normalise_header(c) for c in header]
    found: dict[str, int] = {}

    for field, synonyms in HEADER_SYNONYMS.items():
        for synonym in sorted(synonyms, key=len, reverse=True):
            for index, cell in enumerate(normalised):
                if index in found.values() and field not in found:
                    continue
                if cell == synonym or (synonym in cell and len(cell) <= len(synonym) + 12):
                    found.setdefault(field, index)
                    break
            if field in found:
                break

    if "date" not in found or "narration" not in found:
        return None
    if "debit" not in found and "credit" not in found:
        return None

    return ColumnMap(
        date=found["date"],
        narration=found["narration"],
        reference=found.get("reference"),
        debit=found.get("debit"),
        credit=found.get("credit"),
        balance=found.get("balance"),
        source="header",
    )


def _is_numeric(cell: str | None) -> bool:
    text = (cell or "").strip()
    return bool(text) and bool(_NUMERIC.match(text))


def _date_score(column: Sequence[str | None]) -> float:
    values = [c for c in column if (c or "").strip()]
    if not values:
        return 0.0
    best = 0
    for candidate in CANDIDATES:
        hits = sum(1 for v in values if parse_with(str(v), candidate) is not None)
        best = max(best, hits)
    return best / len(values)


def map_from_content(rows: Sequence[Sequence[str | None]]) -> ColumnMap | None:
    """Content heuristics (PRD 6.1 step 4): a date-parseable column, two numeric
    columns with at most one populated per row, and a roughly monotonic balance."""
    if not rows:
        return None
    width = max(len(r) for r in rows)
    columns = [[(r[i] if i < len(r) else None) for r in rows] for i in range(width)]

    date_scores = [(_date_score(col), i) for i, col in enumerate(columns)]
    date_scores.sort(key=lambda pair: (-pair[0], pair[1]))
    if not date_scores or date_scores[0][0] < 0.8:
        return None
    date_col = date_scores[0][1]

    numeric_cols = [
        i
        for i, col in enumerate(columns)
        if i != date_col and sum(1 for c in col if _is_numeric(c)) >= max(1, len(rows) * 0.5)
    ]
    if len(numeric_cols) < 2:
        return None

    # The balance column is the one that is populated on (almost) every row.
    density = {i: sum(1 for c in columns[i] if _is_numeric(c)) / len(rows) for i in numeric_cols}
    balance_col = max(numeric_cols, key=lambda i: (density[i], i))
    money_cols = [i for i in numeric_cols if i != balance_col]
    if len(money_cols) < 2:
        balance_col = None
        money_cols = numeric_cols[:2]
    else:
        money_cols = sorted(money_cols)[:2]

    narration_candidates = [
        i
        for i in range(width)
        if i != date_col and i not in numeric_cols and any((c or "").strip() for c in columns[i])
    ]
    if not narration_candidates:
        return None
    narration_col = max(
        narration_candidates,
        key=lambda i: (sum(len((c or "").strip()) for c in columns[i]), -i),
    )

    return ColumnMap(
        date=date_col,
        narration=narration_col,
        reference=None,
        debit=money_cols[0],
        credit=money_cols[1],
        balance=balance_col,
        source="content",
    )


def infer_column_map(
    rows: Sequence[Sequence[str | None]], header: Sequence[str | None] | None = None
) -> ColumnMap | None:
    if header:
        mapped = map_from_headers(header)
        if mapped is not None:
            return mapped
    return map_from_content(rows)
