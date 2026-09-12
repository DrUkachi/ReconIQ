from enum import StrEnum
from typing import Any

# PRD section 08. Every non-L4 output is constrained by one of these schemas and
# validated before use. Free text is never parsed with a regex.


class CallSite(StrEnum):
    L1_COLUMN_MAP = "L1_COLUMN_MAP"
    L2_COUNTERPARTY = "L2_COUNTERPARTY"
    L3_EVIDENCE_SUMMARY = "L3_EVIDENCE_SUMMARY"
    L4_ORCHESTRATION = "L4_ORCHESTRATION"
    L5_REPLY_INTENT = "L5_REPLY_INTENT"


class ReplyIntent(StrEnum):
    PROVIDE_EVIDENCE = "PROVIDE_EVIDENCE"
    PROPOSE_RESOLUTION = "PROPOSE_RESOLUTION"
    REASSIGN = "REASSIGN"
    ESCALATE = "ESCALATE"
    ASK_QUESTION = "ASK_QUESTION"
    NOT_RELATED = "NOT_RELATED"
    UNCLEAR = "UNCLEAR"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


def _nullable(*types: str) -> list[str]:
    return [*types, "null"]


COLUMN_MAP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "date_col": {"type": "integer"},
        "narration_col": {"type": "integer"},
        "ref_col": {"type": _nullable("integer")},
        "debit_col": {"type": _nullable("integer")},
        "credit_col": {"type": _nullable("integer")},
        "balance_col": {"type": _nullable("integer")},
    },
    "required": [
        "date_col",
        "narration_col",
        "ref_col",
        "debit_col",
        "credit_col",
        "balance_col",
    ],
    "additionalProperties": False,
}

COUNTERPARTY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"counterparty": {"type": _nullable("string")}},
    "required": ["counterparty"],
    "additionalProperties": False,
}

EVIDENCE_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}

REPLY_INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": [str(i) for i in ReplyIntent]},
        "reason_code": {"type": _nullable("string")},
        "assignee": {"type": _nullable("string")},
        "confidence": {"type": "string", "enum": [str(c) for c in Confidence]},
    },
    "required": ["intent", "reason_code", "assignee", "confidence"],
    "additionalProperties": False,
}

SCHEMAS: dict[CallSite, dict[str, Any]] = {
    CallSite.L1_COLUMN_MAP: COLUMN_MAP_SCHEMA,
    CallSite.L2_COUNTERPARTY: COUNTERPARTY_SCHEMA,
    CallSite.L3_EVIDENCE_SUMMARY: EVIDENCE_SUMMARY_SCHEMA,
    CallSite.L5_REPLY_INTENT: REPLY_INTENT_SCHEMA,
}
