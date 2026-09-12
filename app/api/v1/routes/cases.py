import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import IdempotencyDep, PageDep, PrincipalDep, SessionDep, requires
from app.core.errors import BankReconError, ErrorCode
from app.core.rbac import Action, require
from app.domain.enums import CaseState, EvidenceKind, ProposalState
from app.models.cases import (
    CaseEvidence,
    CaseTransaction,
    ExceptionCase,
    ResolutionProposal,
)
from app.models.core import AppUser, BankTransaction
from app.schemas.api import (
    AddEvidence,
    AssignCase,
    CaseDetail,
    CasePage,
    CreateProposal,
    ReopenCase,
)
from app.services import audit
from app.services.api_mapping import (
    case_summary,
    evidence_out,
    money,
    proposal_out,
    transaction_out,
)
from app.services.cases.transitions import transition_case

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=CasePage)
async def list_cases(
    session: SessionDep,
    principal: PrincipalDep,
    page: PageDep,
    state: str | None = None,
    assignee: uuid.UUID | None = None,
    reconciliation_id: uuid.UUID | None = None,
) -> CasePage:
    statement = select(ExceptionCase).where(
        ExceptionCase.workspace_id == principal.workspace_id
    )
    if state:
        statement = statement.where(ExceptionCase.state == state)
    if assignee:
        statement = statement.where(ExceptionCase.assignee_id == assignee)
    if reconciliation_id:
        statement = statement.where(ExceptionCase.reconciliation_id == reconciliation_id)

    rows = list(
        (
            await session.execute(
                statement.order_by(
                    ExceptionCase.priority, ExceptionCase.created_at
                ).limit(page.limit + 1)
            )
        ).scalars()
    )
    has_more = len(rows) > page.limit
    return CasePage(
        items=[case_summary(c) for c in rows[: page.limit]],
        cursor={"next": None, "has_more": has_more},
    )


@router.get("/{case_id}", response_model=CaseDetail)
async def get_case(
    case_id: uuid.UUID, session: SessionDep, principal: PrincipalDep
) -> CaseDetail:
    case = await _load(session, case_id, principal.workspace_id)

    transactions = list(
        (
            await session.execute(
                select(BankTransaction)
                .join(CaseTransaction, CaseTransaction.bank_transaction_id == BankTransaction.id)
                .where(CaseTransaction.case_id == case_id, CaseTransaction.active.is_(True))
                .order_by(BankTransaction.row_index)
            )
        ).scalars()
    )
    evidence = list(
        (
            await session.execute(
                select(CaseEvidence)
                .where(CaseEvidence.case_id == case_id)
                .order_by(CaseEvidence.created_at)
            )
        ).scalars()
    )
    proposals = list(
        (
            await session.execute(
                select(ResolutionProposal)
                .where(ResolutionProposal.case_id == case_id)
                .order_by(ResolutionProposal.created_at)
            )
        ).scalars()
    )

    requires_approver = case.value_at_risk_minor >= _threshold(principal)
    return CaseDetail(
        **case_summary(case).model_dump(),
        summary=case.summary,
        reconciliation_id=case.reconciliation_id,
        transactions=[transaction_out(t) for t in transactions],
        evidence=[evidence_out(e) for e in evidence],
        proposals=[proposal_out(p, requires_approver=requires_approver) for p in proposals],
        escalated_to=case.escalated_to,
        escalated_at=case.escalated_at,
    )


@router.post("/{case_id}/assign", response_model=CaseDetail)
async def assign_case(
    case_id: uuid.UUID,
    body: AssignCase,
    session: SessionDep,
    principal: PrincipalDep,
    idempotency: IdempotencyDep,
) -> CaseDetail:
    case = await _load(session, case_id, principal.workspace_id)
    target = (
        await session.execute(
            select(AppUser).where(
                AppUser.workspace_id == principal.workspace_id,
                AppUser.slack_user_id == body.assignee_slack_id,
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise BankReconError(ErrorCode.E_USER_NOT_FOUND, slack_id=body.assignee_slack_id)

    require(
        Action.ASSIGN_CASE,
        principal.context(target_user_id=str(target.id)),
    )

    case.assignee_id = target.id
    if body.due_at:
        case.due_at = body.due_at
    await session.flush()

    if CaseState(case.state) in {CaseState.OPEN, CaseState.REOPENED}:
        await transition_case(
            session,
            case_id,
            CaseState.ASSIGNED,
            actor_user_id=principal.user_id,
            actor_slack_id=principal.slack_user_id,
        )
    await session.commit()
    return await get_case(case_id, session, principal)


@router.post("/{case_id}/evidence", response_model=CaseDetail)
async def add_evidence(
    case_id: uuid.UUID,
    body: AddEvidence,
    session: SessionDep,
    principal: PrincipalDep,
    idempotency: IdempotencyDep,
) -> CaseDetail:
    case = await _load(session, case_id, principal.workspace_id)
    require(Action.ADD_EVIDENCE, principal.context())

    session.add(
        CaseEvidence(
            case_id=case.id,
            kind=EvidenceKind.MANUAL_NOTE,
            author_slack_id=principal.slack_user_id,
            excerpt=body.excerpt[:2000],
            permalink=body.permalink,
            added_by=principal.user_id,
            # A human note is still not ledger truth.
            verified=False,
        )
    )
    await audit.record(
        session,
        workspace_id=principal.workspace_id,
        action="EVIDENCE_ADDED",
        actor_user_id=principal.user_id,
        case_id=case.id,
        reconciliation_id=case.reconciliation_id,
    )
    await session.commit()
    return await get_case(case_id, session, principal)


@router.post("/{case_id}/proposals", response_model=CaseDetail)
async def create_proposal(
    case_id: uuid.UUID,
    body: CreateProposal,
    session: SessionDep,
    principal: PrincipalDep,
    idempotency: IdempotencyDep,
) -> CaseDetail:
    case = await _load(session, case_id, principal.workspace_id)
    require(Action.PROPOSE_RESOLUTION, principal.context())

    if not body.evidence_ids:
        raise BankReconError(ErrorCode.E_NO_EVIDENCE)

    session.add(
        ResolutionProposal(
            case_id=case.id,
            reason_code=body.reason_code,
            narrative=body.narrative,
            evidence_ids=[str(e) for e in body.evidence_ids],
            state=ProposalState.PENDING,
            proposed_by=principal.user_id,
            case_version=case.version,
        )
    )
    await session.flush()
    await transition_case(
        session,
        case_id,
        CaseState.PROPOSED,
        actor_user_id=principal.user_id,
        actor_slack_id=principal.slack_user_id,
    )
    await session.commit()
    return await get_case(case_id, session, principal)


@router.post("/{case_id}/reopen", response_model=CaseDetail)
async def reopen_case(
    case_id: uuid.UUID,
    body: ReopenCase,
    session: SessionDep,
    idempotency: IdempotencyDep,
    principal=requires(Action.REOPEN_CASE),
) -> CaseDetail:
    await _load(session, case_id, principal.workspace_id)
    await transition_case(
        session,
        case_id,
        CaseState.REOPENED,
        actor_user_id=principal.user_id,
        actor_slack_id=principal.slack_user_id,
        reason=body.reason,
    )
    await session.commit()
    return await get_case(case_id, session, principal)


async def _load(session, case_id: uuid.UUID, workspace_id: uuid.UUID) -> ExceptionCase:
    case = (
        await session.execute(
            select(ExceptionCase).where(
                ExceptionCase.id == case_id, ExceptionCase.workspace_id == workspace_id
            )
        )
    ).scalar_one_or_none()
    if case is None:
        raise BankReconError(ErrorCode.E_NOT_FOUND, what="that case")
    return case


def _threshold(principal) -> int:
    from app.core.config import get_settings

    return get_settings().approval_value_threshold_minor
