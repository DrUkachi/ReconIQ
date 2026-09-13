import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import CaseState
from app.domain.money import format_minor
from app.models.cases import CaseRecord, CaseTransaction, ExceptionCase
from app.models.core import BankTransaction, PaymentRecordRow, Workspace
from app.services.cases.routing import channel_for
from app.services.outbox import dispatcher
from app.services.slack.blocks import build_case_thread_opener

CASE_THREAD_BUILDER = "case_thread_opener"
UNRESOLVED_STATES = (
    CaseState.OPEN,
    CaseState.ASSIGNED,
    CaseState.AWAITING_INFO,
    CaseState.PROPOSED,
    CaseState.REOPENED,
)


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def enqueue_case_threads(
    session: AsyncSession, *, workspace_id: uuid.UUID, reconciliation_id: uuid.UUID | None = None
) -> int:
    """Queue one opener, in the owning team's channel, per unresolved case without a thread."""
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or not workspace.bot_token or workspace.uninstalled_at:
        return 0
    query = (
        select(ExceptionCase)
        .where(
            ExceptionCase.workspace_id == workspace_id,
            ExceptionCase.state.in_([str(state) for state in UNRESOLVED_STATES]),
            ExceptionCase.slack_thread_ts.is_(None),
        )
        .order_by(ExceptionCase.created_at, ExceptionCase.id)
    )
    if reconciliation_id is not None:
        query = query.where(ExceptionCase.reconciliation_id == reconciliation_id)

    queued = 0
    for case in (await session.execute(query)).scalars().all():
        channel = channel_for(case.type, workspace.case_channels, workspace.recon_channel_id)
        if not channel:
            continue
        message = build_case_thread_opener(
            case_id=str(case.id),
            case_type=str(case.type),
            title=escape(case.title),
            summary=escape(case.summary),
            priority=str(case.priority),
            value_at_risk_minor=case.value_at_risk_minor,
            transactions=await _lines(session, case.id),
            currency=case.currency,
        )
        await dispatcher.enqueue(
            session,
            workspace_id=workspace_id,
            channel_id=channel,
            builder=CASE_THREAD_BUILDER,
            message=message,
            case_id=case.id,
            idempotency_key=f"case-thread:{case.id}",
        )
        queued += 1
    return queued


async def _lines(session: AsyncSession, case_id: uuid.UUID) -> list[str]:
    txns = (
        await session.execute(
            select(BankTransaction)
            .join(CaseTransaction, CaseTransaction.bank_transaction_id == BankTransaction.id)
            .where(CaseTransaction.case_id == case_id)
            .order_by(BankTransaction.row_index)
        )
    ).scalars().all()
    records = (
        await session.execute(
            select(PaymentRecordRow)
            .join(CaseRecord, CaseRecord.payment_record_id == PaymentRecordRow.id)
            .where(CaseRecord.case_id == case_id)
            .order_by(PaymentRecordRow.record_date)
        )
    ).scalars().all()
    lines = [
        f"{t.value_date:%d %b} · {format_minor(t.amount_minor, t.currency)} "
        f"{str(t.direction).lower()} · {escape(t.narration[:80])}"
        for t in txns
    ]
    lines += [
        f"{r.record_date:%d %b} · {format_minor(r.amount_minor, r.currency)} ledger "
        f"{escape(r.external_id or r.reference_norm or '')}"
        for r in records
    ]
    return lines
