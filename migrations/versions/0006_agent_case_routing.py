"""Record which team owns each case, who decided (agent or rule) and why."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = depends_on = None

COLUMNS = (
    ("routed_team", sa.String(16)),
    ("routed_by", sa.String(8)),
    ("routing_confidence", sa.String(8)),
    ("routing_reason", sa.Text()),
)

# Cases already posted were placed by the rule table; record that so the web app shows it.
RULE_TEAMS = {
    "BANK_CHARGE_UNBOOKED": "treasury", "TIMING_DIFFERENCE": "treasury",
    "MISSING_LEDGER_RECORD": "payments", "UNIDENTIFIED_CREDIT": "payments",
    "MISSING_BANK_ENTRY": "payments", "DUPLICATE_BANK_ENTRY": "payments",
    "AMOUNT_MISMATCH": "accounts", "AMBIGUOUS_MATCH": "accounts",
    "EXTRACTION_UNCERTAIN": "accounts", "UNMATCHED_TRANSACTION": "accounts",
}


def upgrade():
    # A regenerated 0001 already creates these columns on fresh databases.
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("exception_case")}
    for name, column_type in COLUMNS:
        if name not in existing:
            op.add_column("exception_case", sa.Column(name, column_type))
    whens = " ".join(f"WHEN '{case_type}' THEN '{team}'" for case_type, team in RULE_TEAMS.items())
    op.execute(
        f"UPDATE exception_case SET routed_team = CASE type {whens} END, routed_by = 'rule', "
        "routing_reason = 'Routed by the rule table before agent routing was enabled.' "
        "WHERE routed_team IS NULL AND slack_thread_ts IS NOT NULL"
    )


def downgrade():
    for name, _ in reversed(COLUMNS):
        op.drop_column("exception_case", name)
