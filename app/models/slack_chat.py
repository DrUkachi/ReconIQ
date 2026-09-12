import uuid

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class SlackChatTurn(Base, TimestampMixin):
    __tablename__ = "slack_chat_turn"
    __table_args__ = (
        UniqueConstraint("workspace_id", "channel_id", "message_ts", name="one_chat_reply_per_message"),
        Index("ix_slack_chat_thread", "workspace_id", "channel_id", "thread_ts"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspace.id"), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    thread_ts: Mapped[str] = mapped_column(String(32), nullable=False)
    message_ts: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_slack_id: Mapped[str] = mapped_column(String(32), nullable=False)
    user_text: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_message: Mapped[dict] = mapped_column(JSONB, nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
