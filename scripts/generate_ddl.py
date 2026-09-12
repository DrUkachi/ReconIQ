"""Regenerate migrations/0001_init.sql from the SQLAlchemy models.

The SQL file is checked in so the schema is reviewable as SQL, but the models
remain the source of truth. Run this after changing any model.
"""

import pathlib

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models import Base

OUT = pathlib.Path(__file__).resolve().parent.parent / "migrations" / "0001_init.sql"

HEADER = """-- BankRecon initial schema. Generated from app/models, then checked in.
-- Regenerate with: python scripts/generate_ddl.py

CREATE EXTENSION IF NOT EXISTS pg_trgm;
"""

FOOTER = """-- PRD section 11: audit is append only, enforced by the database, not by code.
REVOKE UPDATE, DELETE ON audit_event FROM bankrecon_app;

-- Trigram index backing counterparty recall in the evidence search (PRD 6.4).
CREATE INDEX ix_evidence_counterparty_trgm ON conversation_evidence
  USING GIN (array_to_string(counterparties, ' ') gin_trgm_ops);
"""


def render() -> str:
    dialect = postgresql.dialect()
    parts = [HEADER]
    for table in Base.metadata.sorted_tables:
        parts.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            parts.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
        parts.append("")
    parts.append(FOOTER)
    return "\n".join(parts)


if __name__ == "__main__":
    OUT.write_text(render())
    print(f"wrote {OUT}")
