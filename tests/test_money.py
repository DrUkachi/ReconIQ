import pytest

from app.domain.money import (
    AmountLocale,
    detect_currency,
    detect_locale,
    format_minor,
    looks_negative,
    parse_amount,
)

DOT = AmountLocale.DOT_DECIMAL
COMMA = AmountLocale.COMMA_DECIMAL


@pytest.mark.parametrize(
    ("raw", "locale", "expected"),
    [
        ("85,000.00", DOT, 8_500_000),
        ("85,000", DOT, 8_500_000),
        ("85000", DOT, 8_500_000),
        ("1,234,567.89", DOT, 123_456_789),
        ("0.05", DOT, 5),
        ("₦85,000.00", DOT, 8_500_000),
        ("NGN 85,000.00", DOT, 8_500_000),
        ("85,000.00 CR", DOT, 8_500_000),
        ("(85,000.00)", DOT, 8_500_000),
        ("-85,000.00", DOT, 8_500_000),
        ("85.000,00", COMMA, 8_500_000),
        ("1.234.567,89", COMMA, 123_456_789),
    ],
)
def test_parse_amount_locale_cases(raw, locale, expected):
    assert parse_amount(raw, locale) == expected


@pytest.mark.parametrize("raw", ["", "   ", None, "abc", "--", "."])
def test_parse_amount_rejects_junk(raw):
    assert parse_amount(raw, DOT) is None


def test_locale_detected_file_wide_from_one_comma_decimal_row():
    rows = ["85,000.00", "1.234.567,89", "900.00"]
    assert detect_locale(rows) is COMMA


def test_locale_defaults_to_dot_decimal():
    assert detect_locale(["85,000.00", "1,200.00"]) is DOT


def test_sign_is_discarded_because_direction_comes_from_the_column():
    assert parse_amount("-85,000.00", DOT) == parse_amount("85,000.00", DOT)
    assert looks_negative("(85,000.00)") is True
    assert looks_negative("85,000.00") is False


def test_no_float_rounding_drift_on_repeated_parses():
    # 0.1 + 0.2 style drift would show up here if Decimal were not used.
    total = sum(parse_amount("0.10", DOT) for _ in range(10))
    assert total == parse_amount("1.00", DOT)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("₦85,000", "NGN"), ("NGN 85,000", "NGN"), ("$40.00", "USD"), ("85,000", None)],
)
def test_detect_currency(raw, expected):
    assert detect_currency(raw) == expected


def test_format_minor_round_trips_through_the_parser():
    assert format_minor(8_500_000, "NGN") == "₦85,000.00"
    assert parse_amount(format_minor(8_500_000, "NGN"), DOT) == 8_500_000
