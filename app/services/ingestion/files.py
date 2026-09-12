"""I/O for the five-column signed export profile; no persistence or matching."""

import csv
import hashlib
import io
from dataclasses import replace
from pathlib import Path

import pdfplumber

from app.core.config import get_settings
from app.core.errors import BankReconError, ErrorCode
from app.services.extraction.validate import validate_pdf
from app.services.ingestion.signed import HEADERS, ImportResult, SourceRow, parse_signed_rows


def _header(cells) -> bool:
    return tuple(" ".join((c or "").split()).casefold() for c in cells) == tuple(
        h.casefold() for h in HEADERS
    )


def read_ledger_csv(path: Path) -> ImportResult:
    return parse_ledger_csv(path.read_bytes(), path.name)


def parse_ledger_csv(data: bytes, filename: str) -> ImportResult:
    digest = hashlib.sha256(data).hexdigest()
    try:
        reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
        header = next(reader, [])
        if not _header(header):
            raise BankReconError(ErrorCode.E_CSV_SCHEMA, cols=", ".join(header))
        rows = [
            SourceRow(filename, digest, i, None, i, tuple(row))
            for i, row in enumerate(reader, 1)
        ]
    except (UnicodeError, csv.Error) as exc:
        raise BankReconError(ErrorCode.E_CSV_SCHEMA, cols="unreadable CSV") from exc
    if not rows:
        raise BankReconError(ErrorCode.E_CSV_SCHEMA, cols="header only")
    return replace(parse_signed_rows(rows), byte_size=len(data))


def read_signed_pdf(path: Path) -> ImportResult:
    return parse_signed_pdf(path.read_bytes(), path.name)


def parse_signed_pdf(data: bytes, filename: str) -> ImportResult:
    settings = get_settings()
    facts = validate_pdf(
        data, filename, max_bytes=settings.max_pdf_bytes, max_pages=settings.max_pdf_pages,
    )
    rows = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            page_row = 0
            for table in page.extract_tables() or []:
                if not table or not _header(table[0]):
                    # Unrecognized tables cannot silently disappear from an import.
                    raise BankReconError(ErrorCode.E_EXTRACTION_UNREADABLE)
                for cells in table[1:]:
                    if _header(cells):
                        continue
                    page_row += 1
                    rows.append(SourceRow(
                        filename, facts.sha256, len(rows) + 1,
                        page_number, page_row, tuple(cells),
                    ))
            if not page_row:
                raise BankReconError(ErrorCode.E_EXTRACTION_UNREADABLE)
    if not rows:
        raise BankReconError(ErrorCode.E_EXTRACTION_UNREADABLE)
    return replace(parse_signed_rows(rows), byte_size=len(data))
