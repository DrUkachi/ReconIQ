"""Resolution status on reconciliation lines and per-team case channels."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0005"
down_revision = "0004"
branch_labels = depends_on = None

LINE_TABLES = ("bank_transaction", "payment_record")


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    # A regenerated 0001 already creates these columns on fresh databases.
    for table in LINE_TABLES:
        existing = _columns(table)
        if "resolution_status" not in existing:
            op.add_column(table, sa.Column("resolution_status", sa.String(16), nullable=False, server_default="PENDING"))
        if "resolved_at" not in existing:
            op.add_column(table, sa.Column("resolved_at", sa.DateTime(timezone=True)))
        if "resolved_by" not in existing:
            op.add_column(table, sa.Column("resolved_by", pg.UUID(as_uuid=True), sa.ForeignKey("app_user.id")))
        if "resolution_note" not in existing:
            op.add_column(table, sa.Column("resolution_note", sa.Text()))

    # Automatic and confirmed matches need no human decision.
    op.execute("UPDATE bank_transaction SET resolution_status = 'RESOLVED' "
               "WHERE status IN ('AUTO', 'CONFIRMED') AND resolution_status = 'PENDING'")
    op.execute("UPDATE payment_record SET resolution_status = 'RESOLVED' "
               "WHERE status = 'MATCHED' AND resolution_status = 'PENDING'")

    if "case_channels" not in _columns("workspace"):
        op.add_column("workspace", sa.Column("case_channels", pg.JSONB(), nullable=False,
                                             server_default=sa.text("'{}'::jsonb")))


def downgrade():
    op.drop_column("workspace", "case_channels")
    for table in LINE_TABLES:
        for column in ("resolution_note", "resolved_by", "resolved_at", "resolution_status"):
            op.drop_column(table, column)
