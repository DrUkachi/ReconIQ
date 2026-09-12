import json
import logging
import re
import sys
from typing import Any

from app.core.correlation import get_correlation_id

# PRD section 19: structured JSON, one line per event. Amounts redacted at INFO,
# present at DEBUG.

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"xox[baprs]-[A-Za-z0-9-]+"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]+"),
    re.compile(r"sk-or-[A-Za-z0-9_-]+"),
    re.compile(r"\b\d{10}\b"),  # NUBAN account numbers
)

_FIELDS = (
    "workspace_id",
    "actor",
    "component",
    "action",
    "duration_ms",
    "outcome",
    "error_code",
    "reconciliation_id",
    "case_id",
)


def redact(text: str) -> str:
    out = text
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("[redacted]", out)
    return out


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "correlation_id": get_correlation_id(),
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for field in _FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        # Amounts are only ever emitted at DEBUG (PRD 19).
        amount = getattr(record, "amount_minor", None)
        if amount is not None:
            payload["amount_minor"] = amount if record.levelno <= logging.DEBUG else "[redacted]"

        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
