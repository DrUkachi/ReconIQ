import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence

from app.core.errors import BankReconError, ErrorCode


@dataclass(frozen=True)
class DateFormatCandidate:
    name: str
    strptime: str
    # Position of the day component among the numeric fields, used by the >12 rule.
    # None for unambiguous formats (ISO, or those with an alphabetic month).
    day_first: bool | None


# PRD 6.1 names four candidates. MM/DD variants are included because the spec's own
# E_DATE_FORMAT_AMBIGUOUS message ("5 March or 3 May") only arises when they compete.
CANDIDATES: tuple[DateFormatCandidate, ...] = (
    DateFormatCandidate("DD/MM/YYYY", "%d/%m/%Y", True),
    DateFormatCandidate("MM/DD/YYYY", "%m/%d/%Y", False),
    DateFormatCandidate("DD-MM-YYYY", "%d-%m-%Y", True),
    DateFormatCandidate("MM-DD-YYYY", "%m-%d-%Y", False),
    DateFormatCandidate("DD MMM YYYY", "%d %b %Y", None),
    DateFormatCandidate("DD-MMM-YYYY", "%d-%b-%Y", None),
    DateFormatCandidate("YYYY-MM-DD", "%Y-%m-%d", None),
)

_CLEAN_RE = re.compile(r"\s+")
_TWO_DIGIT_YEAR_RE = re.compile(r"^(\d{1,2})([/-])(\d{1,2})\2(\d{2})$")


def _clean(raw: str) -> str:
    text = _CLEAN_RE.sub(" ", str(raw).strip())
    # Expand a two-digit year so a single candidate set covers both widths.
    match = _TWO_DIGIT_YEAR_RE.match(text)
    if match:
        a, sep, b, yy = match.groups()
        century = "20" if int(yy) <= 69 else "19"
        text = f"{a}{sep}{b}{sep}{century}{yy}"
    return text


def _try_parse(raw: str, candidate: DateFormatCandidate) -> date | None:
    try:
        return datetime.strptime(_clean(raw), candidate.strptime).date()
    except ValueError:
        return None


def parse_with(raw: str, candidate: DateFormatCandidate) -> date | None:
    return _try_parse(raw, candidate)


def _is_non_decreasing(values: Sequence[date]) -> bool:
    return all(values[i] <= values[i + 1] for i in range(len(values) - 1))


@dataclass(frozen=True)
class DateInference:
    candidate: DateFormatCandidate
    values: tuple[date, ...]
    monotonic: bool


def infer_date_format(
    raw_dates: Sequence[str], period: tuple[date, date] | None = None
) -> DateInference:
    """Decide one date format for the whole file (PRD 6.1 step 5).

    Prefers the single candidate under which every row parses and dates are
    non-decreasing. Falls back to parse-only agreement when no candidate is
    monotonic, since not every statement is strictly chronological.

    `period` is the caller's period hint (the `period_hint` argument on
    ingest_statement). A statement's rows must fall inside the period it covers,
    which resolves files where every day value is 12 or under and the >12 rule
    therefore cannot fire.
    """
    if not raw_dates:
        raise BankReconError(
            ErrorCode.E_DATE_FORMAT_AMBIGUOUS,
            sample="(no dates)",
            reading_a="unknown",
            reading_b="unknown",
        )

    parsed: dict[str, tuple[date, ...]] = {}
    for candidate in CANDIDATES:
        values = [_try_parse(raw, candidate) for raw in raw_dates]
        if all(v is not None for v in values):
            parsed[candidate.name] = tuple(v for v in values if v is not None)

    if not parsed:
        raise BankReconError(
            ErrorCode.E_DATE_FORMAT_AMBIGUOUS,
            sample=raw_dates[0],
            reading_a="unparseable",
            reading_b="unparseable",
        )

    by_name = {c.name: c for c in CANDIDATES}
    monotonic = [name for name, values in parsed.items() if _is_non_decreasing(values)]
    pool = monotonic or list(parsed)

    if period is not None and len(pool) > 1:
        inside = [
            name
            for name in pool
            if all(period[0] <= value <= period[1] for value in parsed[name])
        ]
        if len(inside) == 1:
            return DateInference(by_name[inside[0]], parsed[inside[0]], bool(monotonic))
        pool = inside or pool

    if len(pool) == 1:
        name = pool[0]
        return DateInference(by_name[name], parsed[name], bool(monotonic))

    resolved = _break_tie(pool, raw_dates, by_name)
    if resolved is not None:
        return DateInference(by_name[resolved], parsed[resolved], bool(monotonic))

    first, second = by_name[pool[0]], by_name[pool[1]]
    sample = _discriminating_sample(raw_dates, first, second)
    raise BankReconError(
        ErrorCode.E_DATE_FORMAT_AMBIGUOUS,
        sample=sample,
        reading_a=_describe(sample, first),
        reading_b=_describe(sample, second),
    )


def _discriminating_sample(
    raw_dates: Sequence[str], first: DateFormatCandidate, second: DateFormatCandidate
) -> str:
    """Quote a row the two readings actually disagree on.

    Asking "is 03/03 the 3rd of March or the 3rd of March?" reads as a bug even
    though the ambiguity is real elsewhere in the file.
    """
    for raw in raw_dates:
        if _try_parse(raw, first) != _try_parse(raw, second):
            return raw
    return raw_dates[0]


def _break_tie(
    pool: list[str], raw_dates: Sequence[str], by_name: dict[str, DateFormatCandidate]
) -> str | None:
    """PRD 6.1: if a day value exceeds 12 under one reading, that reading is the real one."""
    day_first_pool = [n for n in pool if by_name[n].day_first is True]
    month_first_pool = [n for n in pool if by_name[n].day_first is False]
    if not day_first_pool or not month_first_pool:
        # Only one convention in play; prefer ISO, then the first stable candidate.
        for name in ("YYYY-MM-DD", "DD MMM YYYY", "DD-MMM-YYYY"):
            if name in pool:
                return name
        return pool[0] if len(pool) == 1 else None

    leading = [_leading_number(raw) for raw in raw_dates]
    trailing = [_second_number(raw) for raw in raw_dates]
    if any(n is not None and n > 12 for n in leading):
        return day_first_pool[0]
    if any(n is not None and n > 12 for n in trailing):
        return month_first_pool[0]
    return None


def _leading_number(raw: str) -> int | None:
    match = re.match(r"^\s*(\d{1,2})\D", _clean(raw))
    return int(match.group(1)) if match else None


def _second_number(raw: str) -> int | None:
    match = re.match(r"^\s*\d{1,2}\D(\d{1,2})\D", _clean(raw))
    return int(match.group(1)) if match else None


def _describe(raw: str, candidate: DateFormatCandidate) -> str:
    parsed = _try_parse(raw, candidate)
    return f"{parsed.day} {parsed:%B}" if parsed else candidate.name
