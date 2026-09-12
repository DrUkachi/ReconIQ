"""Deterministic intake commands. Document text is data, never an instruction."""

import calendar
import re
from dataclasses import dataclass
from datetime import date

MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})


@dataclass(frozen=True)
class IntakeContext:
    start: date | None = None
    end: date | None = None
    account: str | None = None
    error: str = ""


def is_intake_command(text: str) -> bool:
    clean = re.sub(r"<@[^>]+>", "", text).strip()
    return bool(re.match(r"(?:please\s+)?(?:(?:start|begin|run)\s+(?:a\s+)?)?(reconcile|reconciliation|intake)\b", clean, re.I))


def is_intake_update(event: dict) -> bool:
    if event.get("files") or event.get("type") == "file_shared":
        return True
    clean = re.sub(r"<@[^>]+>", "", event.get("text") or "").strip()
    if is_intake_command(clean) or clean.lower() in {"retry", "cancel", "status"}:
        return True
    if re.search(r"\breplace\s+(ledger|statement|bank)\b", clean, re.I):
        return True
    # Questions about an account or month must not edit the intake context.
    if "?" in clean or re.match(r"(?:what|why|how|when|where|who|can|could|would|is|does|do|explain)\b", clean, re.I):
        return False
    context = parse_context(clean)
    return bool(context.start or context.account or context.error)


def parse_context(text: str) -> IntakeContext:
    accounts = re.findall(r"\baccount\s+(?:(?:ending|last\s*4)\s*[:=]?\s*)?([0-9]{4}|DEMO)\b", text, re.I)
    periods = []
    error = ""
    try:
        ranges = re.findall(r"\b(\d{4}-\d{2}-\d{2})\s+(?:to|through)\s+(\d{4}-\d{2}-\d{2})\b", text, re.I)
        if ranges:
            periods = [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in ranges]
        else:
            months = [(int(y), int(m)) for y, m in re.findall(r"\b(\d{4})-(\d{2})(?!-\d)\b", text)]
            months += [(int(y), MONTHS[m.lower()]) for m, y in re.findall(
                r"\b(" + "|".join(MONTHS) + r")\s+(\d{4})\b", text, re.I,
            )]
            periods = [(date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])) for y, m in months]
        if any(a > b for a, b in periods):
            raise ValueError
    except ValueError:
        error = "The period is invalid. Use August 2026 or 2026-08-01 to 2026-08-31."
    periods = list(dict.fromkeys(periods))
    if len(periods) > 1 or len(set(a.upper() for a in accounts)) > 1:
        error = "More than one account or period was supplied. Give one account and one period for this thread."
    return IntakeContext(
        periods[0][0] if len(periods) == 1 and not error else None,
        periods[0][1] if len(periods) == 1 and not error else None,
        accounts[0].upper() if accounts and not error else None, error,
    )


def file_role(filename: str, message: str) -> str:
    if re.search(r"\b(context|supporting material|guide only)\b", message, re.I):
        return "context"
    if re.search(r"\b(validation only|test ingestion|validate only)\b", message, re.I):
        return "validation"
    name = filename.lower()
    if any(word in name for word in ("guide", "prd", "context")):
        return "context"
    if "edge_case" in name:
        return "validation"
    if name.endswith(".csv"):
        return "ledger"
    if name.endswith(".pdf"):
        return "bank"
    return "unsupported"
