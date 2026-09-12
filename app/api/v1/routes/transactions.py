import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import IdempotencyDep, PrincipalDep, SessionDep, requires
from app.core.errors import BankReconError, ErrorCode
from app.core.rbac import Action
from app.domain.enums import MatchState, TransactionStatus
from app.models.base import utcnow
from app.models.cases import CaseTransaction
from app.models.core import (
    BankTransaction,
    PaymentRecordRow,
    Reconciliation,
    TransactionMatch,
)
from app.schemas.api import CandidateOut, MatchDecision, ScoreComponents, TransactionDetail
from app.services import audit
from app.services.api_mapping import money, transaction_out

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("/{transaction_id}", response_model=TransactionDetail)
async def get_transaction(
    transaction_id: uuid.UUID, session: SessionDep, principal: PrincipalDep
) -> TransactionDetail:
    txn = await _load(session, transaction_id, principal.workspace_id)

    match = (
        await session.execute(
            select(TransactionMatch).where(TransactionMatch.bank_transaction_id == txn.id)
        )
    ).scalar_one_or_none()

    case_link = (
        await session.execute(
            select(CaseTransaction).where(
                CaseTransaction.bank_transaction_id == txn.id,
                CaseTransaction.active.is_(True),
            )
        )
    ).scalar_one_or_none()

    candidates: list[CandidateOut] = []
    if match is not None:
        record = (
            await session.execute(
                select(PaymentRecordRow).where(PaymentRecordRow.id == match.payment_record_id)
            )
        ).scalar_one_or_none()
        if record is not None:
            breakdown = match.breakdown or {}
            candidates.append(
                CandidateOut(
                    payment_record_id=record.id,
                    external_id=record.external_id,
                    record_date=record.record_date,
                    amount=money(record.amount_minor, record.currency),
                    reference=record.reference_norm,
                    counterparty=record.counterparty_norm,
                    score=match.score,
                    breakdown=ScoreComponents(
                        amount=breakdown.get("amount", 0),
                        reference=breakdown.get("reference", 0),
                        date=breakdown.get("date", 0),
                        counterparty=breakdown.get("counterparty", 0),
                        total=breakdown.get("total", match.score),
                    ),
                )
            )

    return TransactionDetail(
        **transaction_out(txn).model_dump(),
        candidates=candidates,
        match_state=MatchState(match.state) if match else None,
        case_id=case_link.case_id if case_link else None,
    )


@router.post("/{transaction_id}/decision", response_model=TransactionDetail)
async def decide_match(
    transaction_id: uuid.UUID,
    body: MatchDecision,
    session: SessionDep,
    idempotency: IdempotencyDep,
    principal=requires(Action.CONFIRM_MATCH),
) -> TransactionDetail:
    """Confirm or reject a review-band candidate.

    The decision is recorded once: a second decider gets E_ALREADY_DECIDED rather
    than silently overwriting the first.
    """
    txn = await _load(session, transaction_id, principal.workspace_id)
    match = (
        await session.execute(
            select(TransactionMatch)
            .where(TransactionMatch.bank_transaction_id == txn.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if match is None:
        raise BankReconError(ErrorCode.E_NOT_FOUND, what="a candidate for that transaction")
    if match.decided_at is not None:
        raise BankReconError(ErrorCode.E_ALREADY_DECIDED, name="Someone")

    confirmed = body.decision == "confirm"
    match.state = MatchState.CONFIRMED if confirmed else MatchState.REJECTED
    match.decided_by = principal.user_id
    match.decided_at = utcnow()
    txn.status = TransactionStatus.CONFIRMED if confirmed else TransactionStatus.UNMATCHED

    await audit.record(
        session,
        workspace_id=principal.workspace_id,
        action="MATCH_DECIDED",
        actor_user_id=principal.user_id,
        reconciliation_id=txn.reconciliation_id,
        to_state=str(match.state),
        detail={"transaction_id": str(txn.id), "decision": body.decision},
    )
    await session.commit()
    return await get_transaction(transaction_id, session, principal)


async def _load(
    session, transaction_id: uuid.UUID, workspace_id: uuid.UUID
) -> BankTransaction:
    txn = (
        await session.execute(
            select(BankTransaction)
            .join(Reconciliation, Reconciliation.id == BankTransaction.reconciliation_id)
            .where(
                BankTransaction.id == transaction_id,
                Reconciliation.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if txn is None:
        raise BankReconError(ErrorCode.E_NOT_FOUND, what="that transaction")
    return txn
