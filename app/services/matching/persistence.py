"""Persist one engine run atomically, with row locking and replay protection."""

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BankReconError, ErrorCode
from app.domain.enums import Direction, MatchState, ReconciliationState, TransactionStatus
from app.domain.records import BankTxn, PaymentRecord
from app.models.base import utcnow
from app.models.cases import CaseMatchKey, CaseRecord, CaseTransaction, ExceptionCase
from app.models.core import BankTransaction, PaymentRecordRow, Reconciliation, TransactionMatch, Workspace
from app.services import audit
from app.services.cases.guards import check_reconciliation_transition
from app.services.exceptions.engine import build_cases
from app.services.listener import cache
from app.services.matching.engine import run_matching
from app.services.matching.scoring import MatchingConfig


async def match_reconciliation(
    session: AsyncSession, *, reconciliation_id: uuid.UUID, workspace_id: uuid.UUID,
) -> dict:
    reconciliation = (await session.execute(select(Reconciliation).where(
        Reconciliation.id == reconciliation_id, Reconciliation.workspace_id == workspace_id,
    ).with_for_update())).scalar_one_or_none()
    if reconciliation is None:
        raise BankReconError(ErrorCode.E_NOT_FOUND, what="that reconciliation")
    if reconciliation.state in (ReconciliationState.AWAITING_ACTION, ReconciliationState.COMPLETE):
        return await matching_summary(session, reconciliation)
    if reconciliation.state != ReconciliationState.MATCHING:
        raise BankReconError(ErrorCode.E_ILLEGAL_TRANSITION, state=reconciliation.state)
    workspace = await session.get(Workspace, workspace_id)
    bank_rows = list((await session.execute(select(BankTransaction).where(
        BankTransaction.reconciliation_id == reconciliation_id,
    ).order_by(BankTransaction.row_index))).scalars())
    ledger_rows = list((await session.execute(select(PaymentRecordRow).where(
        PaymentRecordRow.reconciliation_id == reconciliation_id,
        PaymentRecordRow.workspace_id == workspace_id,
    ).order_by(PaymentRecordRow.id))).scalars())
    if not bank_rows or not ledger_rows:
        raise BankReconError(ErrorCode.E_NO_LEDGER, period=str(reconciliation.period_start))
    for row in [*bank_rows, *ledger_rows]:
        day = row.value_date if isinstance(row, BankTransaction) else row.record_date
        if row.currency != reconciliation.currency or not reconciliation.period_start <= day <= reconciliation.period_end:
            raise BankReconError(ErrorCode.E_VALIDATION, detail="Matching inputs cross currency or period boundaries.")
    txns = [BankTxn(
        id=str(t.id), row_index=t.row_index, value_date=t.value_date, narration=t.narration,
        amount_minor=t.amount_minor, direction=Direction(t.direction), currency=t.currency,
        reference_norm=t.reference_norm, counterparty_norm=t.counterparty_norm,
        balance_minor=t.balance_minor, warnings=tuple(t.warnings),
    ) for t in bank_rows]
    records = [PaymentRecord(
        id=str(r.id), record_date=r.record_date, amount_minor=r.amount_minor,
        direction=Direction(r.direction), currency=r.currency, reference_norm=r.reference_norm,
        counterparty_norm=r.counterparty_norm, external_id=r.external_id,
    ) for r in ledger_rows]
    config = MatchingConfig()
    result = run_matching(txns, records, config)
    drafts = build_cases(txns, records, result, value_threshold_minor=workspace.approval_value_threshold_minor)
    bank_by_id = {str(t.id): t for t in bank_rows}
    ledger_by_id = {str(r.id): r for r in ledger_rows}
    for match in result.matches:
        session.add(TransactionMatch(
            reconciliation_id=reconciliation_id,
            bank_transaction_id=uuid.UUID(match.txn_id), payment_record_id=uuid.UUID(match.record_id),
            score=match.score, method=match.method, state=match.state, breakdown=match.breakdown.as_dict(),
        ))
        bank_by_id[match.txn_id].status = TransactionStatus.AUTO if match.state == MatchState.AUTO else TransactionStatus.REVIEW
        ledger_by_id[match.record_id].status = "MATCHED" if match.state == MatchState.AUTO else "REVIEW"
    for draft in drafts:
        case = ExceptionCase(
            workspace_id=workspace_id, reconciliation_id=reconciliation_id, type=draft.type,
            priority=draft.priority, title=draft.title, summary=draft.summary,
            value_at_risk_minor=draft.value_at_risk_minor, currency=reconciliation.currency,
            due_at=utcnow() + timedelta(hours=draft.due_hours),
        )
        session.add(case)
        await session.flush()
        for txn_id in draft.txn_ids:
            session.add(CaseTransaction(case_id=case.id, bank_transaction_id=uuid.UUID(txn_id)))
            bank_by_id[txn_id].status = TransactionStatus.IN_CASE
        for record_id in draft.record_ids:
            session.add(CaseRecord(case_id=case.id, payment_record_id=uuid.UUID(record_id)))
        for key_type, value in draft.match_keys:
            session.add(CaseMatchKey(case_id=case.id, key_type=key_type, key_value=value))
        await audit.record(
            session, workspace_id=workspace_id, reconciliation_id=reconciliation_id,
            case_id=case.id, action="CASE_CREATED", detail={"type": str(draft.type)},
        )
    check_reconciliation_transition(ReconciliationState(reconciliation.state), ReconciliationState.AWAITING_ACTION)
    reconciliation.state = ReconciliationState.AWAITING_ACTION
    await audit.record(
        session, workspace_id=workspace_id, reconciliation_id=reconciliation_id,
        action="MATCHING_COMPLETED", detail={"matches": len(result.matches), "cases": len(drafts),
            "profile": "existing_deterministic_engine", "date_window_days": config.date_window_days},
    )
    await session.flush()
    cache.invalidate(workspace_id)
    return await matching_summary(session, reconciliation)


async def matching_summary(session: AsyncSession, reconciliation: Reconciliation) -> dict:
    counts = await session.execute(select(BankTransaction.status, func.count()).where(
        BankTransaction.reconciliation_id == reconciliation.id,
    ).group_by(BankTransaction.status))
    cases = await session.scalar(select(func.count()).select_from(ExceptionCase).where(
        ExceptionCase.reconciliation_id == reconciliation.id,
    ))
    return {"id": str(reconciliation.id), "currency": reconciliation.currency,
            "state": str(reconciliation.state), "bank_status_counts": dict(sorted(counts.all())), "cases": cases}
