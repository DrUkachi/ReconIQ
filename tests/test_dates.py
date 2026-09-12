from datetime import date

import pytest

from app.core.errors import BankReconError, ErrorCode
from app.domain.dates import infer_date_format


def test_infers_day_first_when_a_day_exceeds_twelve():
    inference = infer_date_format(["03/03/2026", "25/03/2026", "31/03/2026"])
    assert inference.candidate.name == "DD/MM/YYYY"
    assert inference.values[1] == date(2026, 3, 25)


def test_infers_iso():
    inference = infer_date_format(["2026-03-01", "2026-03-15", "2026-03-31"])
    assert inference.candidate.name == "YYYY-MM-DD"


def test_infers_alphabetic_month():
    inference = infer_date_format(["01 Mar 2026", "15 Mar 2026"])
    assert inference.candidate.name == "DD MMM YYYY"
    assert inference.values[0] == date(2026, 3, 1)


def test_infers_dash_separated_day_first():
    inference = infer_date_format(["03-03-2026", "28-03-2026"])
    assert inference.candidate.name == "DD-MM-YYYY"


def test_monotonicity_breaks_the_tie_when_both_readings_parse():
    # Every day value is <= 12, so only the non-decreasing rule separates these:
    # day-first gives 5 Jan then 3 Feb (rising), month-first gives 1 May then 2 Mar (falling).
    inference = infer_date_format(["05/01/2026", "03/02/2026"])
    assert inference.candidate.name == "DD/MM/YYYY"
    assert inference.monotonic is True


def test_same_month_run_with_no_day_over_twelve_is_reported_ambiguous():
    # 1, 5 and 11 March all read equally well as 3 January, 3 May and 3 November.
    # Neither monotonicity nor the >12 rule separates them, so the spec says ask.
    with pytest.raises(BankReconError) as excinfo:
        infer_date_format(["01/03/2026", "05/03/2026", "11/03/2026"])
    assert excinfo.value.code is ErrorCode.E_DATE_FORMAT_AMBIGUOUS


def test_two_digit_years_are_expanded():
    inference = infer_date_format(["03/03/26", "25/03/26"])
    assert inference.values[0] == date(2026, 3, 3)


def test_genuinely_ambiguous_dates_raise_rather_than_guess():
    # Both readings parse and both are non-decreasing: the spec says ask, not guess.
    with pytest.raises(BankReconError) as excinfo:
        infer_date_format(["01/02/2026", "03/04/2026"])
    assert excinfo.value.code is ErrorCode.E_DATE_FORMAT_AMBIGUOUS


def test_period_hint_resolves_a_file_where_no_day_exceeds_twelve():
    # Day-first reads these as 1 and 3 March; month-first as 2 January and 4 March.
    # Only the day-first reading fits a March statement period.
    inference = infer_date_format(
        ["01/03/2026", "03/03/2026"], period=(date(2026, 3, 1), date(2026, 3, 31))
    )
    assert inference.candidate.name == "DD/MM/YYYY"
    assert inference.values == (date(2026, 3, 1), date(2026, 3, 3))


def test_period_hint_that_fits_neither_reading_still_raises():
    with pytest.raises(BankReconError) as excinfo:
        infer_date_format(
            ["01/02/2026", "03/04/2026"], period=(date(2026, 1, 1), date(2026, 12, 31))
        )
    assert excinfo.value.code is ErrorCode.E_DATE_FORMAT_AMBIGUOUS


def test_unparseable_dates_raise():
    with pytest.raises(BankReconError) as excinfo:
        infer_date_format(["not a date", "also not"])
    assert excinfo.value.code is ErrorCode.E_DATE_FORMAT_AMBIGUOUS


def test_ambiguity_error_message_names_both_readings():
    with pytest.raises(BankReconError) as excinfo:
        infer_date_format(["01/02/2026", "03/04/2026"])
    message = excinfo.value.message
    assert "01/02/2026" in message
    assert "1 February" in message and "2 January" in message
