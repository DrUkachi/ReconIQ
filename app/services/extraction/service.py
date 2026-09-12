import io
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from app.core.config import get_settings
from app.core.errors import BankReconError, ErrorCode
from app.domain.enums import ExtractionMethod
from app.services.extraction.columns import ColumnMap, infer_column_map
from app.services.extraction.parser import ExtractionResult, parse_rows
from app.services.extraction.validate import PdfFacts, validate_pdf

logger = logging.getLogger(__name__)

# PRD 6.1 step 3: a page is treated as scanned below this character density.
MIN_CHARS_PER_PAGE = 50
OCR_PAGE_FRACTION = 0.30

# Detects instruction-shaped content inside a document, PRD section 08 guardrail 3.
_INJECTION_PATTERNS = re.compile(
    r"(ignore (all )?(previous|prior|above) instructions"
    r"|disregard (the )?(above|previous)"
    r"|you are now"
    r"|system prompt"
    r"|close all cases"
    r"|approve (all|every))",
    re.IGNORECASE,
)


@dataclass
class ExtractedDocument:
    facts: PdfFacts
    result: ExtractionResult
    raw_pages: dict[str, str]
    column_map: ColumnMap | None


def detect_instruction_like_content(pages: Sequence[str]) -> bool:
    """Flagged on the statement and mentioned once by the agent. Never acted on."""
    return any(_INJECTION_PATTERNS.search(page or "") for page in pages)


def _page_texts(data: bytes) -> list[str]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [(page.extract_text() or "") for page in pdf.pages]


def needs_ocr(page_texts: Sequence[str]) -> bool:
    """PRD 6.1 step 3: OCR when more than 30% of pages are below the density floor."""
    if not page_texts:
        return True
    sparse = sum(1 for text in page_texts if len(text) < MIN_CHARS_PER_PAGE)
    return sparse / len(page_texts) > OCR_PAGE_FRACTION


def run_ocr(data: bytes, timeout_seconds: int) -> bytes:
    """Subprocess isolation with a hard timeout (threat model: malicious PDF)."""
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "in.pdf"
        target = Path(tmp) / "out.pdf"
        source.write_bytes(data)
        try:
            subprocess.run(
                [
                    "ocrmypdf",
                    "--force-ocr",
                    "--output-type",
                    "pdf",
                    str(source),
                    str(target),
                ],
                check=True,
                capture_output=True,
                timeout=timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise BankReconError(ErrorCode.E_EXTRACTION_UNREADABLE) from exc
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise BankReconError(ErrorCode.E_EXTRACTION_UNREADABLE) from exc
        return target.read_bytes()


def _tables(data: bytes) -> tuple[list[list[str | None]], list[str | None] | None]:
    """pdfplumber table extraction, falling back to word-position clustering."""
    import pdfplumber

    rows: list[list[str | None]] = []
    header: list[str | None] | None = None

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                for row in table:
                    cells = [c if c is None else str(c) for c in row]
                    if header is None and _looks_like_header(cells):
                        header = cells
                        continue
                    if any((c or "").strip() for c in cells):
                        rows.append(cells)
        if not rows:
            for page in pdf.pages:
                rows.extend(_cluster_words(page))

    return rows, header


def _looks_like_header(cells: Sequence[str | None]) -> bool:
    joined = " ".join((c or "").lower() for c in cells)
    return sum(word in joined for word in ("date", "balance", "credit", "debit", "narration")) >= 2


def _cluster_words(page) -> list[list[str | None]]:
    """Group words into rows by y-position, then into columns by x-gap.

    Used only when a statement has no ruled table structure.
    """
    words = page.extract_words() or []
    if not words:
        return []
    lines: dict[int, list[dict]] = {}
    for word in words:
        key = round(word["top"] / 3)
        lines.setdefault(key, []).append(word)

    rows: list[list[str | None]] = []
    for key in sorted(lines):
        line = sorted(lines[key], key=lambda w: w["x0"])
        cells: list[str] = []
        current = line[0]["text"]
        previous_end = line[0]["x1"]
        for word in line[1:]:
            if word["x0"] - previous_end > 12:
                cells.append(current)
                current = word["text"]
            else:
                current += " " + word["text"]
            previous_end = word["x1"]
        cells.append(current)
        rows.append([c for c in cells])
    return rows


def extract_statement(
    data: bytes,
    filename: str = "",
    *,
    column_map_assist=None,
) -> ExtractedDocument:
    """Full extraction pipeline (PRD 6.1).

    `column_map_assist` is the L1 LLM call site, injected so the deterministic path
    is testable without a model and so a model failure degrades to the heuristic map.
    """
    settings = get_settings()
    facts = validate_pdf(
        data,
        filename,
        max_bytes=settings.max_pdf_bytes,
        max_pages=settings.max_pdf_pages,
    )

    page_texts = _page_texts(data)
    method = ExtractionMethod.TEXT_LAYER
    if needs_ocr(page_texts):
        data = run_ocr(data, settings.ocr_timeout_seconds)
        page_texts = _page_texts(data)
        method = ExtractionMethod.OCR
        if needs_ocr(page_texts):
            raise BankReconError(ErrorCode.E_EXTRACTION_UNREADABLE)

    rows, header = _tables(data)
    if not rows:
        raise BankReconError(ErrorCode.E_EXTRACTION_UNREADABLE)

    column_map = infer_column_map(rows, header)
    assist_used = False
    if column_map is None and column_map_assist is not None:
        column_map = column_map_assist(header, rows[:5])
        assist_used = column_map is not None
    if column_map is None:
        raise BankReconError(ErrorCode.E_EXTRACTION_UNREADABLE)

    result = parse_rows(
        rows,
        column_map,
        method=method,
        llm_column_assist_used=assist_used,
    )
    if not result.rows:
        raise BankReconError(ErrorCode.E_EXTRACTION_UNREADABLE)

    if detect_instruction_like_content(page_texts):
        result.warnings.append("instruction_like_content")

    return ExtractedDocument(
        facts=facts,
        result=result,
        raw_pages={str(i): text for i, text in enumerate(page_texts)},
        column_map=column_map,
    )
