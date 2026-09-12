"""Persist signed sources and allow separate currency runs for one export.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE OR REPLACE FUNCTION evidence_counterparty_text(text[]) RETURNS text "
               "LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT array_to_string($1, ' ') $$")
    op.execute("CREATE INDEX IF NOT EXISTS ix_evidence_counterparty_trgm ON conversation_evidence "
               "USING GIN (evidence_counterparty_text(counterparties) gin_trgm_ops)")
    # 0001 reads the regenerated schema on fresh installs. Existing installs need
    # these changes; inspection also makes the fresh-install path a no-op.
    inspector = sa.inspect(op.get_bind())
    if "currency" not in {c["name"] for c in inspector.get_columns("statement")}:
        op.add_column("statement", sa.Column("currency", sa.String(3), nullable=True))
        op.execute("UPDATE statement SET currency = reconciliation.currency "
                   "FROM reconciliation WHERE reconciliation.id = statement.reconciliation_id")
        op.alter_column("statement", "currency", nullable=False)
    for table, name, columns in (
        ("reconciliation", "uniq_period", ["workspace_id", "account_last4", "period_start", "period_end", "currency"]),
        ("statement", "uniq_content", ["workspace_id", "content_sha256", "currency"]),
    ):
        old = next(c for c in inspector.get_unique_constraints(table) if c["name"] == name)
        if old["column_names"] != columns:
            op.drop_constraint(name, table, type_="unique")
            op.create_unique_constraint(name, table, columns)
    if not inspector.has_table("source_import"):
        op.create_table(
            "source_import",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("reconciliation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reconciliation.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(8), nullable=False),
            sa.Column("filename", sa.String(512), nullable=False),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column("byte_size", sa.Integer(), nullable=False),
            sa.Column("raw_rows", postgresql.JSONB(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("reconciliation_id", "kind", name="one_source_per_kind"),
            sa.CheckConstraint("kind IN ('bank', 'ledger')", name="source_kind"),
        )


def downgrade():
    raise RuntimeError("Signed imports cannot be downgraded without losing source provenance.")
