"""Persist thread conversation history and opaque OpenRouter reasoning metadata."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0004"
down_revision = "0003"
branch_labels = depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("slack_chat_turn"):
        return
    op.create_table("slack_chat_turn",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", pg.UUID(as_uuid=True), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("channel_id", sa.String(32), nullable=False),
        sa.Column("thread_ts", sa.String(32), nullable=False),
        sa.Column("message_ts", sa.String(32), nullable=False),
        sa.Column("actor_slack_id", sa.String(32), nullable=False),
        sa.Column("user_text", sa.Text(), nullable=False),
        sa.Column("assistant_message", pg.JSONB(), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("workspace_id", "channel_id", "message_ts", name="one_chat_reply_per_message"),
    )
    op.create_index("ix_slack_chat_thread", "slack_chat_turn", ["workspace_id", "channel_id", "thread_ts"])


def downgrade():
    raise RuntimeError("Conversation history must be retained; downgrade is not supported.")
