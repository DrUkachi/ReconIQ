from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.core.errors import ErrorCode
from app.core.rbac import Action
from app.domain.enums import CaseType, Role

# PRD section 07. Fourteen tools plus two system-only.
#
# Rule T1, the most important rule in the document: the approval path is out of
# band from the model. A `confirm` tool is not in the model's tool list at all.
# The model may only call the corresponding propose_* variant, which emits a Block
# Kit approval; the apply path is triggered exclusively by a verified Slack
# interaction payload whose user id passes the RBAC check in code.


class Autonomy(StrEnum):
    AUTO = "auto"
    CONFIRM = "confirm"
    SYSTEM = "system"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    autonomy: Autonomy
    min_role: Role | None
    rbac_action: Action | None = None
    error_codes: tuple[ErrorCode, ...] = ()
    # For a confirm tool, the proposal tool the model is allowed to call instead.
    propose_variant: str | None = None

    @property
    def model_exposed(self) -> bool:
        return self.autonomy is Autonomy.AUTO

    def to_anthropic(self) -> dict[str, Any]:
        """Strict tool definition: schema-valid arguments are guaranteed by the API."""
        return {
            "name": self.name,
            "description": self.description,
            "strict": True,
            "input_schema": self.input_schema,
        }


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_STR = {"type": "string"}
_INT = {"type": "integer"}


def _nullable_str() -> dict[str, Any]:
    return {"type": ["string", "null"]}


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="ingest_statement",
        description="Ingest a bank statement PDF shared in Slack and start a reconciliation.",
        input_schema=_schema(
            {
                "slack_file_id": _STR,
                "channel_id": _STR,
                "period_hint": _nullable_str(),
            },
            ["slack_file_id", "channel_id", "period_hint"],
        ),
        autonomy=Autonomy.AUTO,
        min_role=Role.APPROVER,
        rbac_action=Action.UPLOAD_STATEMENT,
        error_codes=(
            ErrorCode.E_NOT_PDF,
            ErrorCode.E_PDF_ENCRYPTED,
            ErrorCode.E_DUPLICATE_STATEMENT,
            ErrorCode.E_PDF_TOO_LARGE,
        ),
    ),
    ToolSpec(
        name="load_payment_records",
        description="Load internal payment records for a reconciliation from CSV or the seeded ledger.",
        input_schema=_schema(
            {
                "reconciliation_id": _STR,
                "source": {"type": "string", "enum": ["csv", "seeded"]},
                "slack_file_id": _nullable_str(),
            },
            ["reconciliation_id", "source", "slack_file_id"],
        ),
        autonomy=Autonomy.AUTO,
        min_role=Role.APPROVER,
        rbac_action=Action.LOAD_LEDGER,
        error_codes=(ErrorCode.E_CSV_SCHEMA, ErrorCode.E_NO_RECORDS_FOR_PERIOD),
    ),
    ToolSpec(
        name="run_matching",
        description="Run the deterministic matching engine for a reconciliation.",
        input_schema=_schema({"reconciliation_id": _STR}, ["reconciliation_id"]),
        autonomy=Autonomy.SYSTEM,
        min_role=None,
        error_codes=(ErrorCode.E_NO_LEDGER, ErrorCode.E_ALREADY_MATCHED),
    ),
    ToolSpec(
        name="get_reconciliation",
        description="Get the header statistics and findings for a reconciliation.",
        input_schema=_schema({"reconciliation_id": _nullable_str()}, ["reconciliation_id"]),
        autonomy=Autonomy.AUTO,
        min_role=Role.MEMBER,
        rbac_action=Action.VIEW,
        error_codes=(ErrorCode.E_NOT_FOUND,),
    ),
    ToolSpec(
        name="search_transactions",
        description="Search statement lines. Returns at most 20 rows.",
        input_schema=_schema(
            {
                "reconciliation_id": _STR,
                "status": _nullable_str(),
                "query": _nullable_str(),
                "amount_minor": {"type": ["integer", "null"]},
            },
            ["reconciliation_id", "status", "query", "amount_minor"],
        ),
        autonomy=Autonomy.AUTO,
        min_role=Role.MEMBER,
        rbac_action=Action.VIEW,
        error_codes=(ErrorCode.E_TOO_BROAD,),
    ),
    ToolSpec(
        name="get_transaction",
        description="Get one statement line with its candidates and score breakdown.",
        input_schema=_schema({"transaction_id": _STR}, ["transaction_id"]),
        autonomy=Autonomy.AUTO,
        min_role=Role.MEMBER,
        rbac_action=Action.VIEW,
        error_codes=(ErrorCode.E_NOT_FOUND,),
    ),
    ToolSpec(
        name="search_workspace_evidence",
        description=(
            "Search indexed workspace conversation for messages mentioning an amount, "
            "reference or counterparty. Results are unverified claims, never ledger truth."
        ),
        input_schema=_schema(
            {
                "date_from": _STR,
                "date_to": _STR,
                "amount_minor": {"type": ["integer", "null"]},
                "reference": _nullable_str(),
                "counterparty": _nullable_str(),
            },
            ["date_from", "date_to", "amount_minor", "reference", "counterparty"],
        ),
        autonomy=Autonomy.AUTO,
        min_role=Role.MEMBER,
        rbac_action=Action.VIEW,
    ),
    ToolSpec(
        name="get_case",
        description="Get a case with its transactions, evidence and proposals.",
        input_schema=_schema({"case_id": _STR}, ["case_id"]),
        autonomy=Autonomy.AUTO,
        min_role=Role.MEMBER,
        rbac_action=Action.VIEW,
        error_codes=(ErrorCode.E_NOT_FOUND,),
    ),
    ToolSpec(
        name="create_case",
        description="Group one or more statement lines into an owned exception case.",
        input_schema=_schema(
            {
                "reconciliation_id": _STR,
                "type": {"type": "string", "enum": [str(t) for t in CaseType]},
                "transaction_ids": {"type": "array", "items": _STR},
                "title": _STR,
                "summary": _STR,
            },
            ["reconciliation_id", "type", "transaction_ids", "title", "summary"],
        ),
        autonomy=Autonomy.AUTO,
        min_role=Role.MEMBER,
        rbac_action=Action.CREATE_CASE,
        error_codes=(ErrorCode.E_INVALID_TYPE, ErrorCode.E_TXN_ALREADY_IN_CASE),
    ),
    ToolSpec(
        name="assign_case",
        description="Assign a case to a person. Members may assign only to themselves.",
        input_schema=_schema(
            {"case_id": _STR, "assignee_slack_id": _STR, "due_at": _nullable_str()},
            ["case_id", "assignee_slack_id", "due_at"],
        ),
        autonomy=Autonomy.AUTO,
        min_role=Role.MEMBER,
        rbac_action=Action.ASSIGN_CASE,
        error_codes=(
            ErrorCode.E_AUTHZ,
            ErrorCode.E_USER_NOT_FOUND,
            ErrorCode.E_ILLEGAL_TRANSITION,
        ),
    ),
    ToolSpec(
        name="propose_resolution",
        description="Draft a resolution for a case, citing the evidence it rests on.",
        input_schema=_schema(
            {
                "case_id": _STR,
                "reason_code": _STR,
                "narrative": _STR,
                "evidence_ids": {"type": "array", "items": _STR},
            },
            ["case_id", "reason_code", "narrative", "evidence_ids"],
        ),
        autonomy=Autonomy.AUTO,
        min_role=Role.MEMBER,
        rbac_action=Action.PROPOSE_RESOLUTION,
        error_codes=(ErrorCode.E_ILLEGAL_TRANSITION, ErrorCode.E_NO_EVIDENCE),
    ),
    ToolSpec(
        name="propose_escalation",
        description="Propose escalating a case. Emits an approval for a human to apply.",
        input_schema=_schema(
            {"case_id": _STR, "to_slack_id": _STR, "reason": _STR},
            ["case_id", "to_slack_id", "reason"],
        ),
        autonomy=Autonomy.AUTO,
        min_role=Role.MEMBER,
        rbac_action=Action.ESCALATE,
    ),
    ToolSpec(
        name="propose_match_decision",
        description="Propose confirming or rejecting a review-band match, for approval.",
        input_schema=_schema(
            {
                "transaction_id": _STR,
                "payment_record_id": _STR,
                "decision": {"type": "string", "enum": ["confirm", "reject"]},
            },
            ["transaction_id", "payment_record_id", "decision"],
        ),
        autonomy=Autonomy.AUTO,
        min_role=Role.MEMBER,
        rbac_action=Action.VIEW,
    ),
    # --- confirm tools: never in the model's tool list -------------------------
    ToolSpec(
        name="escalate_case",
        description="Apply an escalation. Reachable only from a verified interaction payload.",
        input_schema=_schema(
            {"case_id": _STR, "to_slack_id": _STR, "reason": _STR},
            ["case_id", "to_slack_id", "reason"],
        ),
        autonomy=Autonomy.CONFIRM,
        min_role=Role.APPROVER,
        rbac_action=Action.ESCALATE,
        error_codes=(ErrorCode.E_AUTHZ, ErrorCode.E_ALREADY_ESCALATED),
        propose_variant="propose_escalation",
    ),
    ToolSpec(
        name="apply_resolution",
        description="Apply an approved resolution and close a case.",
        input_schema=_schema(
            {"proposal_id": _STR, "approver_slack_id": _STR},
            ["proposal_id", "approver_slack_id"],
        ),
        autonomy=Autonomy.CONFIRM,
        min_role=Role.MEMBER,
        rbac_action=Action.APPROVE_RESOLUTION,
        error_codes=(
            ErrorCode.E_AUTHZ,
            ErrorCode.E_VALUE_THRESHOLD,
            ErrorCode.E_STALE_PROPOSAL,
        ),
        propose_variant="propose_resolution",
    ),
    ToolSpec(
        name="decide_match",
        description="Confirm or reject a review-band match.",
        input_schema=_schema(
            {
                "transaction_id": _STR,
                "payment_record_id": _STR,
                "decision": {"type": "string", "enum": ["confirm", "reject"]},
            },
            ["transaction_id", "payment_record_id", "decision"],
        ),
        autonomy=Autonomy.CONFIRM,
        min_role=Role.APPROVER,
        rbac_action=Action.CONFIRM_MATCH,
        error_codes=(ErrorCode.E_AUTHZ, ErrorCode.E_ALREADY_DECIDED),
        propose_variant="propose_match_decision",
    ),
    # --- system-only: not exposed to the model at all --------------------------
    ToolSpec(
        name="post_slack",
        description="Enqueue an outbound Slack message.",
        input_schema=_schema({"channel_id": _STR, "builder": _STR}, ["channel_id", "builder"]),
        autonomy=Autonomy.SYSTEM,
        min_role=None,
    ),
    ToolSpec(
        name="schedule_followup",
        description="Schedule a follow-up nudge for a case.",
        input_schema=_schema({"case_id": _STR, "due_at": _STR}, ["case_id", "due_at"]),
        autonomy=Autonomy.SYSTEM,
        min_role=None,
    ),
)

TOOLS_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in TOOLS}

# Arguments the model is never allowed to supply: identity comes from the
# invocation context, so the model cannot claim to be someone (PRD 07 rule 2).
FORBIDDEN_MODEL_ARGUMENTS: frozenset[str] = frozenset(
    {"actor_user_id", "actor_slack_id", "role", "workspace_id", "approver_slack_id"}
)


def model_tool_definitions() -> list[dict[str, Any]]:
    """The tool list handed to the model. Confirm and system tools are absent."""
    return [t.to_anthropic() for t in TOOLS if t.model_exposed]


def is_model_callable(name: str) -> bool:
    spec = TOOLS_BY_NAME.get(name)
    return spec is not None and spec.model_exposed
