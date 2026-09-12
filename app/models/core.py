import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import (
    Direction,
    ExtractionMethod,
    MatchMethod,
    MatchState,
    ReconciliationState,
    Role,
    TransactionStatus,
)
from app.models.base import Base, TimestampMixin, uuid_pk


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspace"

    id: Mapped[uuid.UUID] = uuid_pk()
    slack_team_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    bot_token: Mapped[str | None] = mapped_column(Text)
    bot_user_id: Mapped[str | None] = mapped_column(String(32))
    slack_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recon_channel_id: Mapped[str | None] = mapped_column(String(32))
    approval_value_threshold_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=50_000_000
    )
    uninstalled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppUser(Base, TimestampMixin):
    __tablename__ = "app_user"
    __table_args__ = (UniqueConstraint("workspace_id", "slack_user_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    slack_user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    # PRD 04: default on first sight of a Slack user.
    role: Mapped[Role] = mapped_column(String(16), nullable=False, default=Role.MEMBER)
    # PRD section 22: stored masked, never in full.
    email_masked: Mapped[str | None] = mapped_column(String(255))


class Reconciliation(Base, TimestampMixin):
    __tablename__ = "reconciliation"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "account_last4",
            "period_start",
            "period_end",
            "currency",
            name="uniq_period",
        ),
        Index("ix_reconciliation_workspace_state", "workspace_id", "state"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    # PRD section 22: only the last four are ever persisted.
    account_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    state: Mapped[ReconciliationState] = mapped_column(
        String(24), nullable=False, default=ReconciliationState.CREATED
    )
    failure_code: Mapped[str | None] = mapped_column(String(48))
    slack_channel_id: Mapped[str | None] = mapped_column(String(32))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Statement(Base, TimestampMixin):
    __tablename__ = "statement"
    __table_args__ = (
        # PRD hard constraint 1: one statement per reconciliation.
        UniqueConstraint("reconciliation_id", name="one_per_recon"),
        UniqueConstraint("workspace_id", "content_sha256", "currency", name="uniq_content"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    reconciliation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reconciliation.id", ondelete="CASCADE"), nullable=False
    )
    slack_file_id: Mapped[str | None] = mapped_column(String(32))
    filename: Mapped[str] = mapped_column(String(512), default="")
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_path: Mapped[str | None] = mapped_column(Text)
    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        String(16), default=ExtractionMethod.TEXT_LAYER
    )
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inferred_date_format: Mapped[str | None] = mapped_column(String(32))
    balance_breaks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Per-page text kept for audit. Never posted to Slack, never sent to the model.
    raw_pages: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BankTransaction(Base, TimestampMixin):
    __tablename__ = "bank_transaction"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="amount_positive"),
        CheckConstraint("direction IN ('CREDIT','DEBIT')", name="dir"),
        Index("ix_bank_transaction_recon_status", "reconciliation_id", "status"),
        Index(
            "ix_bank_transaction_recon_amount_date",
            "reconciliation_id",
            "amount_minor",
            "value_date",
        ),
        UniqueConstraint("reconciliation_id", "row_index"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    reconciliation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reconciliation.id", ondelete="CASCADE"), nullable=False
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    value_date: Mapped[date] = mapped_column(Date, nullable=False)
    narration: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reference_raw: Mapped[str] = mapped_column(String(255), default="")
    reference_norm: Mapped[str] = mapped_column(String(255), default="", index=True)
    counterparty_norm: Mapped[str] = mapped_column(String(255), default="", index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    direction: Mapped[Direction] = mapped_column(String(8), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    balance_minor: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[TransactionStatus] = mapped_column(
        String(16), nullable=False, default=TransactionStatus.UNMATCHED
    )
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)


class PaymentRecordRow(Base, TimestampMixin):
    __tablename__ = "payment_record"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="amount_positive"),
        CheckConstraint("direction IN ('CREDIT','DEBIT')", name="dir"),
        Index(
            "ix_payment_record_open",
            "workspace_id",
            "amount_minor",
            "record_date",
            postgresql_where=text("status = 'OPEN'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    reconciliation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reconciliation.id", ondelete="SET NULL")
    )
    external_id: Mapped[str] = mapped_column(String(128), default="")
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    direction: Mapped[Direction] = mapped_column(String(8), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    reference_raw: Mapped[str] = mapped_column(String(255), default="")
    reference_norm: Mapped[str] = mapped_column(String(255), default="", index=True)
    counterparty_raw: Mapped[str] = mapped_column(String(255), default="")
    counterparty_norm: Mapped[str] = mapped_column(String(255), default="", index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")


class TransactionMatch(Base, TimestampMixin):
    __tablename__ = "transaction_match"
    __table_args__ = (
        UniqueConstraint("bank_transaction_id", name="one_match_per_txn"),
        UniqueConstraint("payment_record_id", name="one_match_per_record"),
        Index("ix_match_recon_state", "reconciliation_id", "state"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    reconciliation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reconciliation.id", ondelete="CASCADE"), nullable=False
    )
    bank_transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_transaction.id", ondelete="CASCADE"), nullable=False
    )
    payment_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payment_record.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[MatchMethod] = mapped_column(String(16), nullable=False)
    state: Mapped[MatchState] = mapped_column(String(16), nullable=False)
    # Component-by-component, so the web app never shows a bare number.
    breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
