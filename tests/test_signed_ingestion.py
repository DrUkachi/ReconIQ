import csv
import hashlib
from collections import defaultdict
from datetime import date
from pathlib import Path

import pytest

from app.core.errors import BankReconError, ErrorCode
from app.domain.enums import Direction
from app.services.ingestion.files import read_ledger_csv, read_signed_pdf
from app.services.ingestion.signed import (
    HEADERS, ImportResult, SourceRow, parse_signed_rows, prepare_matching_inputs,
)
from app.services.matching.engine import run_matching

FIXTURES = Path(__file__).parent / "fixtures" / "signed_exports"
START, END = date(2026, 8, 1), date(2026, 8, 31)
EMPTY = ImportResult((), ())


def source(raw, index=1):
    return SourceRow("test.csv", "digest", index, None, index, tuple(raw))


def totals(imported):
    result = defaultdict(int)
    for row in imported.accepted:
        result[row.currency] += row.signed_minor
    return dict(result)


def test_original_files_import_with_control_totals_and_stable_provenance():
    bank_path = FIXTURES / "Bank_Statement_Demo.pdf"
    ledger_path = FIXTURES / "General_Ledger_Demo.csv"
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (bank_path, ledger_path)}
    bank, ledger = read_signed_pdf(bank_path), read_ledger_csv(ledger_path)
    assert not bank.rejected and not ledger.rejected
    assert (len(bank.accepted), len(ledger.accepted)) == (57, 52)
    assert totals(bank) == {"NGN": 434353111, "USD": -9372500, "EUR": -42500}
    assert totals(ledger) == {"NGN": 281267500, "USD": 370000, "EUR": -42500}
    assert [(r.source.page, r.source.page_row) for r in bank.accepted] == [
        (page, row) for page in range(1, 4) for row in range(1, 20)
    ]
    assert bank.accepted[8].reference == "0007429105"
    assert bank.accepted[12].reference is None
    duplicate_a, duplicate_b = bank.accepted[28:30]
    assert duplicate_a.source.raw == duplicate_b.source.raw
    assert duplicate_a.source.id != duplicate_b.source.id
    assert bank == read_signed_pdf(bank_path)
    assert ledger == read_ledger_csv(ledger_path)
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}


def test_period_and_currency_partition_precede_matching():
    bank = read_signed_pdf(FIXTURES / "Bank_Statement_Demo.pdf")
    ledger = read_ledger_csv(FIXTURES / "General_Ledger_Demo.csv")
    inputs = prepare_matching_inputs(bank, ledger, START, END)
    assert {c: len(v) for c, v in inputs.bank_by_currency.items()} == {
        "NGN": 50, "USD": 4, "EUR": 1,
    }
    assert {c: len(v) for c, v in inputs.ledger_by_currency.items()} == {
        "NGN": 48, "USD": 3, "EUR": 1,
    }
    assert [r.transaction_date for r in inputs.excluded] == [date(2026, 7, 31), date(2026, 9, 1)]
    # Same numeric amount/reference across currencies stays in separate engine runs.
    for currency in inputs.bank_by_currency:
        txns = inputs.bank_by_currency[currency]
        records = inputs.ledger_by_currency[currency]
        assert all(r.currency == currency for r in (*txns, *records))
        result = run_matching(txns, records)
        assert result == run_matching(tuple(reversed(txns)), tuple(reversed(records)))
    ngn = inputs.bank_by_currency["NGN"]
    assert ngn[0].direction == Direction.DEBIT and ngn[0].amount_minor == 7250000
    assert ngn[1].direction == Direction.CREDIT and ngn[1].amount_minor == 18500000
    assert next(t for t in ngn if t.row_index == 12).reference_norm == ""


def test_separate_edge_fixture_quarantines_raw_errors_and_preserves_wrapped_text():
    result = read_signed_pdf(FIXTURES / "Ingestion_Edge_Cases_Demo.pdf")
    assert [r.source.index for r in result.rejected] == list(range(1, 12))
    assert [r.source.index for r in result.accepted] == list(range(12, 17))
    assert result.rejected[3].source.raw[2] == "12O00.00"
    assert result.accepted[0].narration is None
    assert result.accepted[1].currency == "NGN"
    assert result.accepted[1].source.raw[3] == "ngn"
    assert result.accepted[2].reference == "000000008142"
    assert '"Priority" delivery.' in result.accepted[3].narration
    assert "identifiers retained." in result.accepted[3].narration
    assert result.accepted[4].signed_minor == 0
    with pytest.raises(BankReconError) as exc:
        prepare_matching_inputs(result, EMPTY, START, END)
    assert exc.value.code == ErrorCode.E_VALIDATION


@pytest.mark.parametrize("field,value,reason", [
    (0, "2026-02-30", "invalid_iso_date"),
    (0, "08/09/2026", "invalid_iso_date"),
    (0, "2026-8-01", "invalid_iso_date"),
    (0, "", "invalid_iso_date"),
    (2, "", "invalid_decimal_amount"),
    (2, "NaN", "invalid_decimal_amount"),
    (2, "1e3", "invalid_decimal_amount"),
    (2, "(12.00)", "invalid_decimal_amount"),
    (2, "1,250.50", "invalid_decimal_amount"),
    (2, "1.250,50", "invalid_decimal_amount"),
    (2, "1250.005", "invalid_decimal_amount"),
    (2, "92233720368547758.08", "amount_out_of_range"),
    (3, "", "unsupported_or_missing_currency"),
    (3, "ZZZ", "unsupported_or_missing_currency"),
])
def test_strict_fields_are_rejected_without_coercion(field, value, reason):
    raw = ["2026-08-03", "00012", "12.00", "NGN", "Narration"]
    raw[field] = value
    result = parse_signed_rows([source(raw)])
    assert not result.accepted
    assert result.rejected[0].source.raw == tuple(raw)
    assert reason in result.rejected[0].reasons


def test_zero_is_retained_but_not_sent_to_positive_amount_domain_records():
    parsed = parse_signed_rows([source(["2026-08-03", "Z", "0.00", "NGN", "Info"])])
    inputs = prepare_matching_inputs(parsed, EMPTY, START, END)
    assert len(inputs.excluded) == 1
    assert inputs.bank_by_currency == {}


def test_csv_quoted_multiline_text_bom_and_physical_duplicates(tmp_path):
    path = tmp_path / "ledger.csv"
    raw = ["2026-08-03", "00001", "-125.25", "USD", 'A, B\n"quoted"']
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerows([HEADERS, raw, raw])
    result = read_ledger_csv(path)
    assert not result.rejected
    assert len(result.accepted) == 2
    assert result.accepted[0].source.raw == tuple(raw)
    assert result.accepted[0].signed_minor == -12525
    assert result.accepted[0].source.id != result.accepted[1].source.id


def test_malformed_csv_shape_does_not_drop_fields(tmp_path):
    path = tmp_path / "ledger.csv"
    with path.open("w", newline="") as stream:
        csv.writer(stream).writerows([HEADERS, ["2026-08-03", "R", "12.00", "NGN", "text", "extra"]])
    result = read_ledger_csv(path)
    assert not result.accepted
    assert result.rejected[0].reasons == ("expected_five_fields",)


@pytest.mark.parametrize("content", ["wrong,header\n", ",".join(HEADERS) + "\n"])
def test_csv_missing_data_or_wrong_header_is_not_a_success(tmp_path, content):
    path = tmp_path / "ledger.csv"
    path.write_text(content)
    with pytest.raises(BankReconError) as exc:
        read_ledger_csv(path)
    assert exc.value.code == ErrorCode.E_CSV_SCHEMA


def test_invalid_period_is_rejected():
    with pytest.raises(BankReconError, match="period start is after its end"):
        prepare_matching_inputs(EMPTY, EMPTY, END, START)
