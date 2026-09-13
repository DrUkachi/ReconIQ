import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.domain.enums import (
    CaseState,
    CaseType,
    Direction,
    MatchState,
    Priority,
    ReconciliationState,
    ResolutionStatus,
    Role,
    TransactionStatus,
)


class Money(BaseModel):
    """Amounts cross the API as integer minor units plus a rendered string.

    The frontend never does currency arithmetic, and never sees a float.
    """

    minor: int
    currency: str = "NGN"
    display: str


class ReconciliationSummary(BaseModel):
    id: uuid.UUID
    account_last4: str
    period_start: date
    period_end: date
    state: ReconciliationState
    currency: str
    total_rows: int = 0
    matched: int = 0
    review: int = 0
    in_case: int = 0
    unmatched: int = 0
    open_cases: int = 0
    value_at_risk: Money | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class StatementProvenance(BaseModel):
    filename: str
    content_sha256: str
    page_count: int
    extraction_method: str
    confidence: int
    inferred_date_format: str | None = None
    balance_breaks: int
    skipped_rows: int
    warnings: list[str] = Field(default_factory=list)


class ReconciliationDetail(ReconciliationSummary):
    statement: StatementProvenance | None = None
    completion_blockers: list[str] = Field(default_factory=list)


class AuditEventOut(BaseModel):
    id: uuid.UUID
    action: str
    actor_user_id: uuid.UUID | None = None
    actor_slack_id: str | None = None
    case_id: uuid.UUID | None = None
    from_state: str | None = None
    to_state: str | None = None
    reason: str | None = None
    detail: dict = Field(default_factory=dict)
    created_at: datetime


class ScoreComponents(BaseModel):
    amount: int
    reference: int
    date: int
    counterparty: int
    total: int


class CandidateOut(BaseModel):
    payment_record_id: uuid.UUID
    external_id: str
    record_date: date
    amount: Money
    reference: str
    counterparty: str
    score: int
    breakdown: ScoreComponents


class TransactionOut(BaseModel):
    id: uuid.UUID
    row_index: int
    value_date: date
    narration: str
    reference: str
    counterparty: str
    amount: Money
    direction: Direction
    status: TransactionStatus
    balance: Money | None = None
    warnings: list[str] = Field(default_factory=list)
    resolution_status: ResolutionStatus = ResolutionStatus.PENDING
    resolved_at: datetime | None = None
    resolution_note: str | None = None


class TransactionDetail(TransactionOut):
    candidates: list[CandidateOut] = Field(default_factory=list)
    match_state: MatchState | None = None
    case_id: uuid.UUID | None = None


class EvidenceOut(BaseModel):
    id: uuid.UUID
    kind: str
    author_slack_id: str | None = None
    excerpt: str
    permalink: str | None = None
    matched_on: list[str] = Field(default_factory=list)
    score: int | None = None
    # Workspace evidence is never ledger truth. The UI must render this marker.
    verified: bool = False
    created_at: datetime | None = None


class ProposalOut(BaseModel):
    id: uuid.UUID
    reason_code: str
    narrative: str
    state: str
    evidence_ids: list[str] = Field(default_factory=list)
    proposed_by: uuid.UUID | None = None
    decided_by: uuid.UUID | None = None
    decided_at: datetime | None = None
    requires_approver: bool = False


class CaseSummary(BaseModel):
    id: uuid.UUID
    type: CaseType
    state: CaseState
    priority: Priority
    title: str
    value_at_risk: Money
    assignee_id: uuid.UUID | None = None
    due_at: datetime | None = None
    permalink: str | None = None
    version: int = 0
    resolution_status: ResolutionStatus = ResolutionStatus.PENDING
    slack_channel_id: str | None = None


class CaseDetail(CaseSummary):
    summary: str
    reconciliation_id: uuid.UUID
    transactions: list[TransactionOut] = Field(default_factory=list)
    evidence: list[EvidenceOut] = Field(default_factory=list)
    proposals: list[ProposalOut] = Field(default_factory=list)
    escalated_to: uuid.UUID | None = None
    escalated_at: datetime | None = None


class Cursor(BaseModel):
    next: str | None = None
    has_more: bool = False


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    cursor: Cursor


class CasePage(BaseModel):
    items: list[CaseSummary]
    cursor: Cursor


class TransactionListItem(TransactionOut):
    """A statement line with the run and the case (if any) that it belongs to."""

    currency: str
    reconciliation_id: uuid.UUID
    account_last4: str
    period_start: date
    period_end: date
    case_id: uuid.UUID | None = None
    case_type: CaseType | None = None
    case_state: CaseState | None = None
    case_permalink: str | None = None


class TransactionListPage(BaseModel):
    """Numbered pages rather than a cursor, so the web table can jump to any page."""

    items: list[TransactionListItem]
    page: int
    page_size: int
    total: int
    pages: int
    # Counts under every filter except resolution_status, for the Pending/Resolved tabs.
    resolution_counts: dict[str, int] = Field(default_factory=dict)
    currencies: list[str] = Field(default_factory=list)


# --- request bodies ---------------------------------------------------------


class CreateReconciliation(BaseModel):
    account_last4: str = Field(min_length=1, max_length=4)
    period_start: date
    period_end: date
    currency: str = "NGN"


class MatchDecision(BaseModel):
    payment_record_id: uuid.UUID
    decision: str = Field(pattern="^(confirm|reject)$")


class AssignCase(BaseModel):
    assignee_slack_id: str
    due_at: datetime | None = None


class AddEvidence(BaseModel):
    excerpt: str = Field(min_length=1, max_length=2000)
    permalink: str | None = None


class CreateProposal(BaseModel):
    reason_code: str
    narrative: str = Field(min_length=1)
    evidence_ids: list[uuid.UUID] = Field(default_factory=list)


class ProposalDecision(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    note: str | None = None


class ReopenCase(BaseModel):
    reason: str = Field(min_length=1)


class SettingsOut(BaseModel):
    approval_value_threshold: Money
    auto_match_threshold: int
    review_floor: int
    ambiguity_gap: int
    date_window_days: int
    listener_threshold: int
    recon_channel_id: str | None = None


class SettingsUpdate(BaseModel):
    approval_value_threshold_minor: int | None = Field(default=None, ge=0)
    recon_channel_id: str | None = None


class RoleUpdate(BaseModel):
    slack_user_id: str
    role: Role


class SessionLogin(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    name: str | None = Field(default=None, max_length=255)
    workspace_name: str | None = Field(default=None, max_length=255)


class SessionUserOut(BaseModel):
    id: uuid.UUID
    display_name: str
    email_masked: str | None = None
    role: Role
    slack_user_id: str


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str


class SessionOut(BaseModel):
    user: SessionUserOut
    workspace: WorkspaceOut


class LogoutOut(BaseModel):
    ok: bool = True
