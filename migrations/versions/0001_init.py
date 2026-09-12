"""Initial schema.

Applies the checked-in migrations/0001_init.sql so the SQL file and the migration
cannot drift: there is exactly one rendering of the schema, generated from the
models by scripts/generate_ddl.py.

Revision ID: 0001
Revises:
"""

import pathlib

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL_FILE = pathlib.Path(__file__).resolve().parent.parent / "0001_init.sql"

# The REVOKE in 0001_init.sql targets the bankrecon_app role. Create it first so a
# fresh database migrates cleanly; in production the role already exists and this
# is a no-op.
ENSURE_ROLE = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'bankrecon_app') THEN
        CREATE ROLE bankrecon_app NOLOGIN;
    END IF;
END
$$;
"""


def upgrade() -> None:
    op.execute(ENSURE_ROLE)
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    raise NotImplementedError(
        "The initial schema is not reversible. Drop the database instead."
    )
