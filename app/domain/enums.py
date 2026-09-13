from enum import StrEnum


class Direction(StrEnum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class Role(StrEnum):
    MEMBER = "member"
    APPROVER = "approver"
    OWNER = "owner"


ROLE_RANK: dict[Role, int] = {Role.MEMBER: 0, Role.APPROVER: 1, Role.OWNER: 2}


class ReconciliationState(StrEnum):
    CREATED = "CREATED"
    EXTRACTING = "EXTRACTING"
    MATCHING = "MATCHING"
    AWAITING_ACTION = "AWAITING_ACTION"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class CaseState(StrEnum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    AWAITING_INFO = "AWAITING_INFO"
    PROPOSED = "PROPOSED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


# States in which a case still participates in the StandingCaseListener, PRD 6.5 step 1.
LISTENABLE_CASE_STATES: frozenset[CaseState] = frozenset(
    {CaseState.OPEN, CaseState.ASSIGNED, CaseState.AWAITING_INFO}
)

TERMINAL_CASE_STATES: frozenset[CaseState] = frozenset({CaseState.CLOSED})


class CaseType(StrEnum):
    DUPLICATE_BANK_ENTRY = "DUPLICATE_BANK_ENTRY"
    EXTRACTION_UNCERTAIN = "EXTRACTION_UNCERTAIN"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    TIMING_DIFFERENCE = "TIMING_DIFFERENCE"
    BANK_CHARGE_UNBOOKED = "BANK_CHARGE_UNBOOKED"
    MISSING_LEDGER_RECORD = "MISSING_LEDGER_RECORD"
    UNIDENTIFIED_CREDIT = "UNIDENTIFIED_CREDIT"
    MISSING_BANK_ENTRY = "MISSING_BANK_ENTRY"
    UNMATCHED_TRANSACTION = "UNMATCHED_TRANSACTION"


class ResolutionStatus(StrEnum):
    """Per statement or ledger line: PENDING until matched or its case is confirmed resolved."""

    PENDING = "PENDING"
    RESOLVED = "RESOLVED"


class Priority(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# PRD section 6.3, due date offsets in hours.
PRIORITY_DUE_HOURS: dict[Priority, int] = {
    Priority.CRITICAL: 4,
    Priority.HIGH: 24,
    Priority.MEDIUM: 48,
    Priority.LOW: 120,
}


class TransactionStatus(StrEnum):
    UNMATCHED = "UNMATCHED"
    AUTO = "AUTO"
    REVIEW = "REVIEW"
    CONFIRMED = "CONFIRMED"
    IN_CASE = "IN_CASE"
    IGNORED = "IGNORED"


class MatchMethod(StrEnum):
    EXACT = "EXACT"
    SCORED = "SCORED"
    MANUAL = "MANUAL"


class MatchState(StrEnum):
    AUTO = "AUTO"
    REVIEW = "REVIEW"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class ExtractionMethod(StrEnum):
    TEXT_LAYER = "TEXT_LAYER"
    OCR = "OCR"


class EvidenceKind(StrEnum):
    LISTENER_HIT = "LISTENER_HIT"
    ON_DEMAND_SEARCH = "ON_DEMAND_SEARCH"
    THREAD_REPLY = "THREAD_REPLY"
    MANUAL_NOTE = "MANUAL_NOTE"
    ATTACHED_CLAIM = "ATTACHED_CLAIM"


class MatchKeyType(StrEnum):
    AMOUNT = "AMOUNT"
    REF = "REF"
    INVOICE = "INVOICE"
    COUNTERPARTY = "COUNTERPARTY"


class JobState(StrEnum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    DONE = "DONE"
    FAILED = "FAILED"


class OutboxState(StrEnum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    SENT = "SENT"
    FAILED = "FAILED"


class ProposalState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ResolutionReasonCode(StrEnum):
    PAID_LATE = "PAID_LATE"
    BANK_ERROR = "BANK_ERROR"
    LEDGER_OMISSION = "LEDGER_OMISSION"
    DUPLICATE_REVERSED = "DUPLICATE_REVERSED"
    FEE_ACCEPTED = "FEE_ACCEPTED"
    COUNTERPARTY_CONFIRMED = "COUNTERPARTY_CONFIRMED"
    WRITTEN_OFF = "WRITTEN_OFF"
    NOT_OUR_TRANSACTION = "NOT_OUR_TRANSACTION"
