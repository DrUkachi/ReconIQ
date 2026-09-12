"""Durable Slack intake and retryable outbox delivery.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0003"
down_revision = "0002"
branch_labels = depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "bot_user_id" not in {c["name"] for c in inspector.get_columns("workspace")}:
        op.add_column("workspace", sa.Column("bot_user_id", sa.String(32)))
    if "slack_retry_at" not in {c["name"] for c in inspector.get_columns("workspace")}:
        op.add_column("workspace", sa.Column("slack_retry_at", sa.DateTime(timezone=True)))
    columns = {c["name"] for c in inspector.get_columns("slack_outbox")}
    if "available_at" not in columns:
        op.add_column("slack_outbox", sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    if "idempotency_key" not in columns:
        op.add_column("slack_outbox", sa.Column("idempotency_key", sa.String(255)))
        op.create_unique_constraint("uq_slack_outbox_idempotency_key", "slack_outbox", ["idempotency_key"])
    if not inspector.has_table("slack_intake"):
        op.create_table(
            "slack_intake",
            sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
            sa.Column("workspace_id", pg.UUID(as_uuid=True), sa.ForeignKey("workspace.id"), nullable=False),
            sa.Column("actor_user_id", pg.UUID(as_uuid=True), sa.ForeignKey("app_user.id"), nullable=False),
            sa.Column("channel_id", sa.String(32), nullable=False),
            sa.Column("thread_ts", sa.String(32), nullable=False),
            sa.Column("account_last4", sa.String(4)),
            sa.Column("period_start", sa.Date()), sa.Column("period_end", sa.Date()),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("selected_files", pg.JSONB(), nullable=False),
            sa.Column("reconciliation_ids", pg.JSONB(), nullable=False),
            sa.Column("last_prompt", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("workspace_id", "channel_id", "thread_ts", name="one_intake_per_thread"),
        )
    if not inspector.has_table("slack_intake_file"):
        op.create_table(
            "slack_intake_file",
            sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
            sa.Column("intake_id", pg.UUID(as_uuid=True), sa.ForeignKey("slack_intake.id", ondelete="CASCADE"), nullable=False),
            sa.Column("slack_file_id", sa.String(32), nullable=False),
            sa.Column("filename", sa.String(512), nullable=False),
            sa.Column("role", sa.String(16), nullable=False),
            sa.Column("state", sa.String(16), nullable=False),
            sa.Column("content", sa.LargeBinary()), sa.Column("sha256", sa.String(64)),
            sa.Column("report", pg.JSONB(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("intake_id", "slack_file_id", name="one_intake_file"),
        )


def downgrade():
    raise RuntimeError("Slack intake history cannot be discarded by a downgrade.")
