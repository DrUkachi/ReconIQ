import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class SourceImport(Base, TimestampMixin):
    """Original extracted fields, including rows outside the selected currency/period.

    One immutable bank source and ledger snapshot per reconciliation. The service
    rejects replacement bytes instead of changing the source beneath a match.
    """

    __tablename__ = "source_import"
    __table_args__ = (
        UniqueConstraint("reconciliation_id", "kind", name="one_source_per_kind"),
        CheckConstraint("kind IN ('bank', 'ledger')", name="source_kind"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    reconciliation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reconciliation.id", ondelete="CASCADE"), nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_rows: Mapped[list] = mapped_column(JSONB, nullable=False)
