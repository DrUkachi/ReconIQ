import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class SlackIntake(Base, TimestampMixin):
    __tablename__ = "slack_intake"
    __table_args__ = (UniqueConstraint("workspace_id", "channel_id", "thread_ts", name="one_intake_per_thread"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspace.id"), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    thread_ts: Mapped[str] = mapped_column(String(32), nullable=False)
    account_last4: Mapped[str | None] = mapped_column(String(4))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="WAITING", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    selected_files: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    reconciliation_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    last_prompt: Mapped[str] = mapped_column(String(64), default="", nullable=False)


class SlackIntakeFile(Base, TimestampMixin):
    __tablename__ = "slack_intake_file"
    __table_args__ = (UniqueConstraint("intake_id", "slack_file_id", name="one_intake_file"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    intake_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("slack_intake.id", ondelete="CASCADE"), nullable=False)
    slack_file_id: Mapped[str] = mapped_column(String(32), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    # Bounded original bytes make retries/restarts independent of expiring file URLs.
    content: Mapped[bytes | None] = mapped_column(LargeBinary)
    sha256: Mapped[str | None] = mapped_column(String(64))
    report: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
