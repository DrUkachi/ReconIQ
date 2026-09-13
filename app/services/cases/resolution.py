import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import ResolutionStatus
from app.models.base import utcnow
from app.models.cases import CaseRecord, CaseTransaction
from app.models.core import BankTransaction, PaymentRecordRow


async def set_case_lines_resolution(
    session: AsyncSession,
    case_id: uuid.UUID,
    status: ResolutionStatus,
    *,
    actor_user_id: uuid.UUID | None = None,
    note: str | None = None,
) -> None:
    """Keep each owned statement and ledger line's Resolution Status in step with its case."""
    resolved = status is ResolutionStatus.RESOLVED
    values = {
        "resolution_status": str(status),
        "resolved_at": utcnow() if resolved else None,
        "resolved_by": actor_user_id if resolved else None,
        "resolution_note": note if resolved else None,
    }
    txn_ids = select(CaseTransaction.bank_transaction_id).where(CaseTransaction.case_id == case_id)
    record_ids = select(CaseRecord.payment_record_id).where(CaseRecord.case_id == case_id)
    await session.execute(
        update(BankTransaction).where(BankTransaction.id.in_(txn_ids)).values(**values),
        execution_options={"synchronize_session": "fetch"},
    )
    await session.execute(
        update(PaymentRecordRow).where(PaymentRecordRow.id.in_(record_ids)).values(**values),
        execution_options={"synchronize_session": "fetch"},
    )
