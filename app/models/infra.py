import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
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

from app.domain.enums import JobState, OutboxState
from app.models.base import Base, TimestampMixin, uuid_pk


class AuditEvent(Base):
    """Append-only. UPDATE and DELETE are revoked from the app role in migration 0001.

    References IDs and amounts rather than documents, so it survives statement
    deletion under the retention policy (PRD section 22).
    """

    __tablename__ = "audit_event"
    __table_args__ = (
        Index("ix_audit_recon_created", "reconciliation_id", "created_at"),
        Index("ix_audit_case_created", "case_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    reconciliation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reconciliation.id", ondelete="SET NULL")
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("exception_case.id", ondelete="SET NULL")
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    actor_slack_id: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str | None] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uniq_idem"),
        Index("ix_job_pending", "state", "created_at", postgresql_where=text("state = 'PENDING'")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[JobState] = mapped_column(String(16), nullable=False, default=JobState.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Leases are reaped by the scheduler after 10 minutes (PRD 6.8).
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SlackOutbox(Base):
    """Every outbound Slack call. State is never contingent on a successful post."""

    __tablename__ = "slack_outbox"
    __table_args__ = (
        Index(
            "ix_outbox_pending",
            "state",
            "created_at",
            postgresql_where=text("state = 'PENDING'"),
        ),
        Index("ix_outbox_channel", "channel_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("exception_case.id", ondelete="SET NULL")
    )
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    thread_ts: Mapped[str | None] = mapped_column(String(32))
    builder: Mapped[str] = mapped_column(String(64), nullable=False)
    blocks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    fallback_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    state: Mapped[OutboxState] = mapped_column(
        String(16), nullable=False, default=OutboxState.PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Presence of message_ts is the sent marker; it makes double-send detectable.
    message_ts: Mapped[str | None] = mapped_column(String(32))
    permalink: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProcessedEvent(Base):
    """Slack event dedupe (PRD section 14). The event id is the primary key."""

    __tablename__ = "processed_event"

    slack_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False, default="")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProcessedInteraction(Base):
    """Interaction payload replay guard, deduped on trigger_id and kept 24h."""

    __tablename__ = "processed_interaction"

    trigger_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IdempotencyRecord(Base):
    """Replayed for 24 hours on every mutating REST endpoint (PRD section 12)."""

    __tablename__ = "idempotency_record"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(128), primary_key=True)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
