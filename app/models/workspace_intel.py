import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import Direction
from app.models.base import Base, TimestampMixin, uuid_pk


class ConversationEvidence(Base, TimestampMixin):
    """One indexed workspace message (PRD 6.4).

    Section 22: normalised signals and a 200 character excerpt only. Full message
    bodies are never stored.
    """

    __tablename__ = "conversation_evidence"
    __table_args__ = (
        UniqueConstraint("workspace_id", "channel_id", "ts", name="uniq_message"),
        Index("ix_evidence_amounts", "amounts_minor", postgresql_using="gin"),
        Index("ix_evidence_refs", "refs_norm", postgresql_using="gin"),
        Index("ix_evidence_invoices", "invoices", postgresql_using="gin"),
        Index("ix_evidence_posted", "workspace_id", "posted_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    ts: Mapped[str] = mapped_column(String(32), nullable=False)
    thread_ts: Mapped[str | None] = mapped_column(String(32))
    author_slack_id: Mapped[str] = mapped_column(String(32), nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    excerpt: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    permalink: Mapped[str | None] = mapped_column(Text)

    amounts_minor: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), nullable=False, default=list
    )
    refs_norm: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    invoices: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    counterparties: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    # message_deleted tombstones the row rather than removing it, so an evidence
    # link on a closed case never dangles.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkspaceClaim(Base, TimestampMixin):
    """A structured, UNVERIFIED assertion extracted from workspace conversation.

    Participates in evidence matching. Never participates in payment_record
    matching, and can never close a case on its own (PRD section 03).
    """

    __tablename__ = "workspace_claim"
    __table_args__ = (Index("ix_claim_workspace_amount", "workspace_id", "claimed_amount_minor"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    conversation_evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversation_evidence.id", ondelete="CASCADE"), nullable=False
    )
    claimed_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    claimed_direction: Mapped[Direction | None] = mapped_column(String(8))
    claimed_reference: Mapped[str | None] = mapped_column(String(255))
    claimed_counterparty: Mapped[str | None] = mapped_column(String(255))
    claimed_date: Mapped[date | None] = mapped_column(Date)
    author_slack_id: Mapped[str] = mapped_column(String(32), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ListenerSuppression(Base):
    """Written when a user clicks "Not related" (PRD 6.5 step 6).

    Suppresses that message and any later message from the same author carrying
    the same key for that case.
    """

    __tablename__ = "listener_suppression"
    __table_args__ = (Index("ix_suppression_lookup", "case_id", "author_slack_id", "key_value"),)

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_case.id", ondelete="CASCADE"), primary_key=True
    )
    author_slack_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    key_value: Mapped[str] = mapped_column(String(255), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ListenerNotification(Base):
    """Ledger of agent-initiated listener posts, for the rate limits in PRD 6.5 step 5."""

    __tablename__ = "listener_notification"
    __table_args__ = (
        Index("ix_listener_notification_case", "case_id", "created_at"),
        Index("ix_listener_notification_workspace", "workspace_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_case.id", ondelete="CASCADE"), nullable=False
    )
    conversation_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversation_evidence.id", ondelete="SET NULL")
    )
    score: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
