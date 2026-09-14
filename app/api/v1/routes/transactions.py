import math
import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import IdempotencyDep, PrincipalDep, SessionDep, requires
from app.core.errors import BankReconError, ErrorCode
from app.core.rbac import Action
from app.domain.enums import MatchState, ResolutionStatus, TransactionStatus
from app.models.base import utcnow
from app.models.cases import CaseTransaction, ExceptionCase
from app.models.core import (
    BankTransaction,
    PaymentRecordRow,
    Reconciliation,
    TransactionMatch,
)
from app.schemas.api import (
    CandidateOut,
    MatchDecision,
    ScoreComponents,
    TransactionDetail,
    TransactionListItem,
    TransactionListPage,
)
from app.services import audit
from app.services.api_mapping import money, transaction_out

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=TransactionListPage)
async def list_all_transactions(
    session: SessionDep,
    principal: PrincipalDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    resolution_status: ResolutionStatus | None = None,
    status: TransactionStatus | None = None,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    reconciliation_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> TransactionListPage:
    """Every statement line in the workspace, newest first, one numbered page at a time."""
    in_workspace = (Reconciliation.id == BankTransaction.reconciliation_id) & (
        Reconciliation.workspace_id == principal.workspace_id
    )
    filters = []
    if status:
        filters.append(BankTransaction.status == status)
    if currency:
        filters.append(BankTransaction.currency == currency.upper())
    if reconciliation_id:
        filters.append(BankTransaction.reconciliation_id == reconciliation_id)
    if q and q.strip():
        term = q.strip()
        filters.append(
            BankTransaction.narration.icontains(term, autoescape=True)
            | BankTransaction.reference_norm.icontains(term, autoescape=True)
            | BankTransaction.counterparty_norm.icontains(term, autoescape=True)
        )

    counts = {
        str(key): int(value)
        for key, value in (
            await session.execute(
                select(BankTransaction.resolution_status, func.count())
                .join(Reconciliation, in_workspace)
                .where(*filters)
                .group_by(BankTransaction.resolution_status)
            )
        ).all()
    }
    if resolution_status:
        filters.append(BankTransaction.resolution_status == resolution_status)
        total = counts.get(str(resolution_status), 0)
    else:
        total = sum(counts.values())
    pages = max(1, math.ceil(total / page_size))
    page = min(page, pages)

    rows = (
        await session.execute(
            select(BankTransaction, Reconciliation)
            .join(Reconciliation, in_workspace)
            .where(*filters)
            .order_by(
                BankTransaction.value_date.desc(),
                Reconciliation.currency,
                BankTransaction.row_index,
                BankTransaction.id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    cases: dict[uuid.UUID, ExceptionCase] = {}
    if rows:
        links = await session.execute(
            select(CaseTransaction.bank_transaction_id, ExceptionCase)
            .join(ExceptionCase, ExceptionCase.id == CaseTransaction.case_id)
            .where(CaseTransaction.bank_transaction_id.in_([txn.id for txn, _ in rows]))
            # Later rows win: an active link over a historical one, then the newest case.
            .order_by(CaseTransaction.active, ExceptionCase.created_at)
        )
        for txn_id, case in links.all():
            cases[txn_id] = case

    currencies = (
        await session.execute(
            select(Reconciliation.currency)
            .where(Reconciliation.workspace_id == principal.workspace_id)
            .distinct()
            .order_by(Reconciliation.currency)
        )
    ).scalars().all()

    items = []
    for txn, reconciliation in rows:
        case = cases.get(txn.id)
        items.append(
            TransactionListItem(
                **transaction_out(txn).model_dump(),
                currency=txn.currency,
                reconciliation_id=reconciliation.id,
                account_last4=reconciliation.account_last4,
                period_start=reconciliation.period_start,
                period_end=reconciliation.period_end,
                case_id=case.id if case else None,
                case_type=case.type if case else None,
                case_state=case.state if case else None,
                case_permalink=case.permalink if case else None,
                case_routed_team=case.routed_team if case else None,
            )
        )
    return TransactionListPage(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        pages=pages,
        resolution_counts=counts,
        currencies=list(currencies),
    )


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
    record = await session.get(PaymentRecordRow, match.payment_record_id)
    for line in (txn, record):
        if line is None:
            continue
        line.resolution_status = ResolutionStatus.RESOLVED if confirmed else ResolutionStatus.PENDING
        line.resolved_at = utcnow() if confirmed else None
        line.resolved_by = principal.user_id if confirmed else None
        line.resolution_note = "MATCH_CONFIRMED" if confirmed else None

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
