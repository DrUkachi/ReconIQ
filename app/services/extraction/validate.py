import hashlib
import io
from dataclasses import dataclass

from app.core.errors import BankReconError, ErrorCode

PDF_MAGIC = b"%PDF"


@dataclass(frozen=True)
class PdfFacts:
    sha256: str
    byte_size: int
    page_count: int


def validate_pdf(
    data: bytes, filename: str = "", *, max_bytes: int, max_pages: int
) -> PdfFacts:
    """PRD 6.1 step 1. Every rejection is a taxonomy code with a user-facing message.

    Also the first line of the malicious-PDF control: size and page caps are applied
    before any parser sees the bytes.
    """
    if not data[:4] == PDF_MAGIC:
        extension = filename.rsplit(".", 1)[-1].upper() if "." in filename else "unrecognised"
        raise BankReconError(ErrorCode.E_NOT_PDF, ext=extension)

    if len(data) > max_bytes:
        raise BankReconError(
            ErrorCode.E_PDF_TOO_LARGE, size_mb=round(len(data) / (1024 * 1024), 1)
        )

    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise BankReconError(ErrorCode.E_PDF_ENCRYPTED)
        page_count = len(reader.pages)
    except BankReconError:
        raise
    except (PdfReadError, Exception) as exc:
        raise BankReconError(ErrorCode.E_EXTRACTION_UNREADABLE) from exc

    if page_count > max_pages:
        raise BankReconError(ErrorCode.E_PDF_TOO_LARGE, size_mb=round(len(data) / (1024 * 1024), 1))

    return PdfFacts(
        sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        page_count=page_count,
    )
