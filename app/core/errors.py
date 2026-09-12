from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    # Extraction / intake, PRD section 15.
    E_NOT_PDF = "E_NOT_PDF"
    E_PDF_ENCRYPTED = "E_PDF_ENCRYPTED"
    E_PDF_TOO_LARGE = "E_PDF_TOO_LARGE"
    E_EXTRACTION_UNREADABLE = "E_EXTRACTION_UNREADABLE"
    E_DATE_FORMAT_AMBIGUOUS = "E_DATE_FORMAT_AMBIGUOUS"
    E_MIXED_CURRENCY = "E_MIXED_CURRENCY"
    E_DUPLICATE_STATEMENT = "E_DUPLICATE_STATEMENT"
    E_NO_LEDGER = "E_NO_LEDGER"
    E_CSV_SCHEMA = "E_CSV_SCHEMA"
    E_NO_RECORDS_FOR_PERIOD = "E_NO_RECORDS_FOR_PERIOD"
    E_AMBIGUOUS_MATCH = "E_AMBIGUOUS_MATCH"

    # Authorisation and lifecycle.
    E_AUTHZ = "E_AUTHZ"
    E_VALUE_THRESHOLD = "E_VALUE_THRESHOLD"
    E_STALE_PROPOSAL = "E_STALE_PROPOSAL"
    E_ILLEGAL_TRANSITION = "E_ILLEGAL_TRANSITION"
    E_COMPLETION_BLOCKED = "E_COMPLETION_BLOCKED"
    E_ALREADY_ESCALATED = "E_ALREADY_ESCALATED"
    E_ALREADY_DECIDED = "E_ALREADY_DECIDED"
    E_ALREADY_MATCHED = "E_ALREADY_MATCHED"
    E_TXN_ALREADY_IN_CASE = "E_TXN_ALREADY_IN_CASE"
    E_NO_EVIDENCE = "E_NO_EVIDENCE"
    E_INVALID_TYPE = "E_INVALID_TYPE"

    # Infrastructure degradation.
    E_LLM_UNAVAILABLE = "E_LLM_UNAVAILABLE"
    E_LLM_BUDGET = "E_LLM_BUDGET"
    E_SLACK_UNAVAILABLE = "E_SLACK_UNAVAILABLE"
    E_AGENT_TURN_BUDGET = "E_AGENT_TURN_BUDGET"
    E_FILE_NOT_VISIBLE = "E_FILE_NOT_VISIBLE"

    # Generic lookup / validation.
    E_NOT_FOUND = "E_NOT_FOUND"
    E_USER_NOT_FOUND = "E_USER_NOT_FOUND"
    E_TOO_BROAD = "E_TOO_BROAD"
    E_VALIDATION = "E_VALIDATION"
    E_INTERNAL_AUTH = "E_INTERNAL_AUTH"


@dataclass(frozen=True)
class ErrorSpec:
    """A code's HTTP status and the user-facing message template from PRD section 15.

    `template` is formatted with the params passed to BankReconError, so every
    placeholder must be supplied at raise time.
    """

    http_status: int
    template: str


ERROR_SPECS: dict[ErrorCode, ErrorSpec] = {
    ErrorCode.E_NOT_PDF: ErrorSpec(
        400, "That is a {ext} file. I read PDF statements, and CSV for payment records."
    ),
    ErrorCode.E_PDF_ENCRYPTED: ErrorSpec(
        400, "This PDF is password protected. Can you upload an unlocked copy?"
    ),
    ErrorCode.E_PDF_TOO_LARGE: ErrorSpec(
        413, "That file is {size_mb}MB. My limit is 10MB. Can you split it by month?"
    ),
    ErrorCode.E_EXTRACTION_UNREADABLE: ErrorSpec(
        422,
        "I could not read this reliably, and I will not guess at figures. "
        "Can you upload the CSV export instead?",
    ),
    ErrorCode.E_DATE_FORMAT_AMBIGUOUS: ErrorSpec(
        422,
        "I cannot tell whether {sample} is {reading_a} or {reading_b} in this statement. "
        "Which is it?",
    ),
    ErrorCode.E_MIXED_CURRENCY: ErrorSpec(
        422,
        "This statement has both {currencies} lines. I handle one currency per reconciliation.",
    ),
    ErrorCode.E_DUPLICATE_STATEMENT: ErrorSpec(
        409, "I reconciled this exact file on {date}. Re-run it?"
    ),
    ErrorCode.E_NO_LEDGER: ErrorSpec(
        409,
        "I have the statement. I do not have {period} payment records. "
        "Drop the CSV here and I will continue.",
    ),
    ErrorCode.E_CSV_SCHEMA: ErrorSpec(
        422,
        "I need columns for date, amount, and reference. I found: {cols}. Map them for me?",
    ),
    ErrorCode.E_NO_RECORDS_FOR_PERIOD: ErrorSpec(
        422, "No payment records fall inside {period}."
    ),
    ErrorCode.E_AMBIGUOUS_MATCH: ErrorSpec(
        409, "Two records fit this {amount} equally well. I am not going to guess."
    ),
    ErrorCode.E_AUTHZ: ErrorSpec(403, "Only {names} can approve this."),
    ErrorCode.E_VALUE_THRESHOLD: ErrorSpec(
        403, "This case is {amount}, above the {threshold} limit. It needs @{approver}."
    ),
    ErrorCode.E_STALE_PROPOSAL: ErrorSpec(409, "{name} already decided this {time} ago."),
    ErrorCode.E_ILLEGAL_TRANSITION: ErrorSpec(409, "That case is already {state}."),
    ErrorCode.E_COMPLETION_BLOCKED: ErrorSpec(
        409,
        "I cannot close {period} yet. {n} cases are open and {m} matches are undecided.",
    ),
    ErrorCode.E_ALREADY_ESCALATED: ErrorSpec(409, "That case is already escalated to {name}."),
    ErrorCode.E_ALREADY_DECIDED: ErrorSpec(409, "That match was already decided by {name}."),
    ErrorCode.E_ALREADY_MATCHED: ErrorSpec(409, "Matching has already run for this reconciliation."),
    ErrorCode.E_TXN_ALREADY_IN_CASE: ErrorSpec(
        409, "Transaction {transaction_id} already belongs to an open case."
    ),
    ErrorCode.E_NO_EVIDENCE: ErrorSpec(
        422, "A resolution needs at least one piece of evidence attached."
    ),
    ErrorCode.E_INVALID_TYPE: ErrorSpec(422, "{value} is not a case type I recognise."),
    ErrorCode.E_LLM_UNAVAILABLE: ErrorSpec(
        503,
        "Conversational answers are unavailable right now. The reconciliation itself completed.",
    ),
    ErrorCode.E_LLM_BUDGET: ErrorSpec(
        429, "This run hit its model call budget. The deterministic result is unaffected."
    ),
    ErrorCode.E_SLACK_UNAVAILABLE: ErrorSpec(
        503, "Slack posts are queued and will deliver when Slack responds."
    ),
    ErrorCode.E_AGENT_TURN_BUDGET: ErrorSpec(
        200, "I am going in circles on this one. Here is what I have so far."
    ),
    ErrorCode.E_FILE_NOT_VISIBLE: ErrorSpec(
        404, "I cannot see that file. Share it in a channel I am in and I will pick it up."
    ),
    ErrorCode.E_NOT_FOUND: ErrorSpec(404, "I cannot find {what}."),
    ErrorCode.E_USER_NOT_FOUND: ErrorSpec(404, "I do not know the user {slack_id}."),
    ErrorCode.E_TOO_BROAD: ErrorSpec(
        422, "That search returns {n} rows. Narrow it and I will show you the detail."
    ),
    ErrorCode.E_VALIDATION: ErrorSpec(422, "{detail}"),
    ErrorCode.E_INTERNAL_AUTH: ErrorSpec(
        401, "This API only accepts requests from the RekonIQ web app."
    ),
}


class BankReconError(Exception):
    """Every failure in the system carries a code from the taxonomy.

    Params supply the placeholders in the code's message template. A missing
    placeholder degrades to the raw template rather than raising inside an
    error path.
    """

    def __init__(self, code: ErrorCode, **params: Any) -> None:
        self.code = code
        self.params: dict[str, Any] = params
        super().__init__(f"{code}: {self.message}")

    @property
    def spec(self) -> ErrorSpec:
        return ERROR_SPECS[self.code]

    @property
    def http_status(self) -> int:
        return self.spec.http_status

    @property
    def message(self) -> str:
        try:
            return self.spec.template.format(**self.params)
        except (KeyError, IndexError):
            return self.spec.template

    def to_payload(self, correlation_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": str(self.code),
            "message": self.message,
            "details": self.params,
        }
        if correlation_id:
            payload["correlation_id"] = correlation_id
        return payload


@dataclass(frozen=True)
class AuthzDenial:
    """Structured refusal returned to the model, PRD rule A1. Never raises to the user."""

    code: ErrorCode = ErrorCode.E_AUTHZ
    message: str = ""
    allowed_roles: tuple[str, ...] = field(default_factory=tuple)
