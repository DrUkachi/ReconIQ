import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BankReconError, ErrorCode
from app.domain.enums import CaseState, ProposalState
from app.models.base import utcnow
from app.models.cases import ExceptionCase, ResolutionProposal
from app.services import audit
from app.services.cases.guards import CaseGuardContext, check_case_transition
from app.services.listener import cache as listener_cache

# PRD rule S1: there is no other way to change case.state in this codebase.
# Enforced by tests/test_transition_chokepoint.py, which greps for direct writes.


async def transition_case(
    session: AsyncSession,
    case_id: uuid.UUID,
    to_state: CaseState,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_slack_id: str | None = None,
    reason: str | None = None,
    expected_version: int | None = None,
    agent_requested_info: bool = False,
    assignee_replied: bool = False,
) -> ExceptionCase:
    """Lock the row, check the guard table, write the audit event, invalidate the cache.

    expected_version implements the optimistic lock from PRD section 14: a caller
    that read the case at version N is told to retry rather than silently
    overwriting a concurrent edit.
    """
    case = (
        await session.execute(
            select(ExceptionCase).where(ExceptionCase.id == case_id).with_for_update()
        )
    ).scalar_one_or_none()
    if case is None:
        raise BankReconError(ErrorCode.E_NOT_FOUND, what="that case")

    if expected_version is not None and case.version != expected_version:
        raise BankReconError(ErrorCode.E_STALE_PROPOSAL, name="Someone else", time="just now")

    from_state = CaseState(case.state)

    approved = await _has_approved_proposal(session, case_id)
    pending = await _has_pending_proposal(session, case_id)

    check_case_transition(
        from_state,
        to_state,
        CaseGuardContext(
            has_assignee=case.assignee_id is not None,
            has_pending_proposal=pending,
            proposal_approved=approved,
            reason=reason,
            agent_requested_info=agent_requested_info,
            assignee_replied=assignee_replied,
        ),
    )

    case.state = to_state
    case.version += 1
    if to_state is CaseState.CLOSED:
        case.closed_at = utcnow()
    if to_state is CaseState.REOPENED:
        case.reopened_reason = reason

    await audit.record(
        session,
        workspace_id=case.workspace_id,
        action="CASE_TRANSITION",
        actor_user_id=actor_user_id,
        actor_slack_id=actor_slack_id,
        reconciliation_id=case.reconciliation_id,
        case_id=case.id,
        from_state=str(from_state),
        to_state=str(to_state),
        reason=reason,
    )
    await session.flush()

    # The listener key set is cached in memory; any state change may add or remove
    # this case from the listenable set (PRD 6.5 step 1).
    listener_cache.invalidate(case.workspace_id)
    return case


async def _has_pending_proposal(session: AsyncSession, case_id: uuid.UUID) -> bool:
    result = await session.execute(
        select(ResolutionProposal.id).where(
            ResolutionProposal.case_id == case_id,
            ResolutionProposal.state == ProposalState.PENDING,
        )
    )
    return result.first() is not None


async def _has_approved_proposal(session: AsyncSession, case_id: uuid.UUID) -> bool:
    result = await session.execute(
        select(ResolutionProposal.id).where(
            ResolutionProposal.case_id == case_id,
            ResolutionProposal.state == ProposalState.APPROVED,
        )
    )
    return result.first() is not None
