import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import IdempotencyDep, PrincipalDep, SessionDep
from app.core.errors import BankReconError, ErrorCode
from app.core.rbac import Action, require
from app.domain.enums import CaseState, ProposalState
from app.models.base import utcnow
from app.models.cases import ExceptionCase, ResolutionProposal
from app.schemas.api import ProposalDecision, ProposalOut
from app.services import audit
from app.services.api_mapping import proposal_out
from app.services.cases.transitions import transition_case

router = APIRouter(prefix="/proposals", tags=["proposals"])


@router.post("/{proposal_id}/decision", response_model=ProposalOut)
async def decide_proposal(
    proposal_id: uuid.UUID,
    body: ProposalDecision,
    session: SessionDep,
    principal: PrincipalDep,
    idempotency: IdempotencyDep,
) -> ProposalOut:
    """Approve or reject a proposed resolution.

    PRD section 14: the proposal row is locked, so the second of two simultaneous
    approvers is told who beat them rather than double-applying the resolution.
    """
    proposal = (
        await session.execute(
            select(ResolutionProposal)
            .where(ResolutionProposal.id == proposal_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise BankReconError(ErrorCode.E_NOT_FOUND, what="that proposal")

    case = (
        await session.execute(
            select(ExceptionCase).where(
                ExceptionCase.id == proposal.case_id,
                ExceptionCase.workspace_id == principal.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if case is None:
        raise BankReconError(ErrorCode.E_NOT_FOUND, what="that case")

    if proposal.state is not ProposalState.PENDING:
        raise BankReconError(
            ErrorCode.E_STALE_PROPOSAL, name="Someone", time="moments"
        )

    from app.core.config import get_settings

    threshold = get_settings().approval_value_threshold_minor
    require(
        Action.APPROVE_RESOLUTION,
        principal.context(
            assignee_user_id=str(case.assignee_id) if case.assignee_id else None,
            value_at_risk_minor=case.value_at_risk_minor,
            threshold_minor=threshold,
        ),
    )

    approved = body.decision == "approve"
    proposal.state = ProposalState.APPROVED if approved else ProposalState.REJECTED
    proposal.decided_by = principal.user_id
    proposal.decided_at = utcnow()
    await session.flush()

    if approved:
        await transition_case(
            session,
            case.id,
            CaseState.RESOLVED,
            actor_user_id=principal.user_id,
            actor_slack_id=principal.slack_user_id,
            reason=body.note,
        )
        # PRD section 10: RESOLVED to CLOSED is automatic, in the same transaction.
        await transition_case(
            session,
            case.id,
            CaseState.CLOSED,
            actor_user_id=principal.user_id,
            actor_slack_id=principal.slack_user_id,
        )
    else:
        await transition_case(
            session,
            case.id,
            CaseState.ASSIGNED,
            actor_user_id=principal.user_id,
            actor_slack_id=principal.slack_user_id,
        )

    await audit.record(
        session,
        workspace_id=principal.workspace_id,
        action="PROPOSAL_DECIDED",
        actor_user_id=principal.user_id,
        case_id=case.id,
        reconciliation_id=case.reconciliation_id,
        to_state=str(proposal.state),
        reason=body.note,
    )
    await session.commit()
    return proposal_out(
        proposal, requires_approver=case.value_at_risk_minor >= threshold
    )
