import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import CaseState, CaseType, EvidenceKind, MatchKeyType, Priority, ProposalState
from app.models.base import Base, TimestampMixin, uuid_pk


class ExceptionCase(Base, TimestampMixin):
    __tablename__ = "exception_case"
    __table_args__ = (
        # One case, one Slack thread. The thread is the case file (PRD mechanism M3).
        UniqueConstraint("slack_channel_id", "slack_thread_ts", name="uniq_thread"),
        Index("ix_case_workspace_state", "workspace_id", "state"),
        Index("ix_case_assignee_state", "assignee_id", "state"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    reconciliation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reconciliation.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[CaseType] = mapped_column(String(32), nullable=False)
    state: Mapped[CaseState] = mapped_column(String(16), nullable=False, default=CaseState.OPEN)
    priority: Mapped[Priority] = mapped_column(String(16), nullable=False, default=Priority.MEDIUM)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    value_at_risk_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")

    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # PRD section 10: escalation is an attribute, never a state.
    escalated_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    slack_channel_id: Mapped[str | None] = mapped_column(String(32))
    slack_thread_ts: Mapped[str | None] = mapped_column(String(32))
    permalink: Mapped[str | None] = mapped_column(Text)

    # PRD section 14: optimistic locking for concurrent case edits.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reopened_reason: Mapped[str | None] = mapped_column(Text)


class CaseTransaction(Base):
    __tablename__ = "case_transaction"
    __table_args__ = (
        # PRD section 11: a transaction belongs to at most one OPEN case. Partial on
        # `active`, which the app clears when a case closes, so a reopened period can
        # re-file the same row without dropping the historical link.
        Index(
            "one_open_case_per_txn",
            "bank_transaction_id",
            unique=True,
            postgresql_where=text("active"),
        ),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_case.id", ondelete="CASCADE"), primary_key=True
    )
    bank_transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_transaction.id", ondelete="CASCADE"), primary_key=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class CaseRecord(Base):
    """Ledger rows attached to a case, for MISSING_BANK_ENTRY."""

    __tablename__ = "case_record"

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_case.id", ondelete="CASCADE"), primary_key=True
    )
    payment_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payment_record.id", ondelete="CASCADE"), primary_key=True
    )


class CaseMatchKey(Base):
    """Denormalised keys the StandingCaseListener intersects against (PRD 6.5 step 1).

    Rebuilt on case creation and whenever transactions are added or removed.
    """

    __tablename__ = "case_match_key"
    __table_args__ = (Index("ix_case_match_key_lookup", "key_type", "key_value"),)

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_case.id", ondelete="CASCADE"), primary_key=True
    )
    key_type: Mapped[MatchKeyType] = mapped_column(String(16), primary_key=True)
    key_value: Mapped[str] = mapped_column(String(255), primary_key=True)


class CaseEvidence(Base, TimestampMixin):
    __tablename__ = "case_evidence"
    __table_args__ = (Index("ix_case_evidence_case", "case_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_case.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[EvidenceKind] = mapped_column(String(24), nullable=False)
    conversation_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversation_evidence.id", ondelete="SET NULL")
    )
    author_slack_id: Mapped[str | None] = mapped_column(String(32))
    excerpt: Mapped[str] = mapped_column(Text, default="")
    permalink: Mapped[str | None] = mapped_column(Text)
    matched_on: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    score: Mapped[int | None] = mapped_column(Integer)
    # Workspace evidence is unverified by construction. The UI must render this.
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    added_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))


class ResolutionProposal(Base, TimestampMixin):
    __tablename__ = "resolution_proposal"
    __table_args__ = (Index("ix_proposal_case_state", "case_id", "state"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_case.id", ondelete="CASCADE"), nullable=False
    )
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    state: Mapped[ProposalState] = mapped_column(
        String(16), nullable=False, default=ProposalState.PENDING
    )
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Pinned to the case version the proposal was written against (PRD section 14).
    case_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
