"""Verified Slack button clicks: the only path that applies a proposed resolution (PRD rule T1)."""
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.core.errors import BankReconError, ErrorCode
from app.core.rbac import Action, AuthzContext, require
from app.domain.enums import CaseState, ProposalState, ResolutionStatus, Role
from app.domain.money import format_minor
from app.models.base import utcnow
from app.models.cases import ExceptionCase, ResolutionProposal
from app.models.core import AppUser, Workspace
from app.services import audit
from app.services.cases.comments import slack_actor
from app.services.cases.resolution import set_case_lines_resolution
from app.services.cases.transitions import transition_case
from app.services.outbox import dispatcher

logger = logging.getLogger(__name__)

DECISIONS = {"apply_resolution": ProposalState.APPROVED, "reject_resolution": ProposalState.REJECTED}


async def handle_interaction(job, *, sessionmaker=None) -> None:
    payload = job.payload or {}
    handler = payload.get("handler")
    if handler not in DECISIONS:
        logger.info("interaction_not_supported", extra={"component": "slack", "action": str(handler)})
        return
    try:
        proposal_id = uuid.UUID(str(payload.get("value")))
    except ValueError:
        return
    actor_slack_id = payload.get("actor_slack_id") or ""
    if not actor_slack_id:
        return

    factory = sessionmaker or get_sessionmaker()
    async with factory() as session, session.begin():
        workspace = await session.get(Workspace, job.workspace_id)
        if workspace is None or workspace.uninstalled_at or payload.get("team_id") != workspace.slack_team_id:
            return
        proposal = await session.scalar(
            select(ResolutionProposal).where(ResolutionProposal.id == proposal_id).with_for_update()
        )
        if proposal is None:
            return
        case = await session.scalar(
            select(ExceptionCase).where(ExceptionCase.id == proposal.case_id, ExceptionCase.workspace_id == workspace.id)
        )
        if case is None:
            return
        click_key = payload.get("message_ts") or ""
        actor = await slack_actor(session, workspace.id, actor_slack_id)

        if proposal.state != ProposalState.PENDING:
            decider = await session.get(AppUser, proposal.decided_by) if proposal.decided_by else None
            who = f"<@{decider.slack_user_id}>" if decider else "someone"
            await _say(session, workspace, case, payload,
                       f"This proposal was already {str(proposal.state).lower()} by {who}.",
                       key=f"stale:{proposal.id}:{actor_slack_id}:{click_key}")
            return

        try:
            require(
                Action.APPROVE_RESOLUTION,
                AuthzContext(
                    role=Role(actor.role),
                    actor_user_id=str(actor.id),
                    assignee_user_id=str(case.assignee_id) if case.assignee_id else None,
                    value_at_risk_minor=case.value_at_risk_minor,
                    threshold_minor=workspace.approval_value_threshold_minor,
                ),
            )
        except BankReconError as exc:
            await audit.record_authz_denied(
                session, workspace_id=workspace.id, action=handler,
                actor_user_id=actor.id, actor_slack_id=actor_slack_id, case_id=case.id,
            )
            if exc.code is ErrorCode.E_VALUE_THRESHOLD:
                reason = (f"this case is {format_minor(case.value_at_risk_minor, case.currency)}, above the "
                          f"{format_minor(workspace.approval_value_threshold_minor, case.currency)} limit, so an approver must decide it.")
            else:
                reason = "only the case assignee or an approver can decide this proposal."
            await _say(session, workspace, case, payload, f"<@{actor_slack_id}>, {reason}",
                       key=f"denied:{proposal.id}:{actor_slack_id}:{click_key}")
            return

        proposal.state = DECISIONS[handler]
        proposal.decided_by = actor.id
        proposal.decided_at = utcnow()
        await session.flush()

        if proposal.state == ProposalState.APPROVED:
            await transition_case(session, case.id, CaseState.RESOLVED, actor_user_id=actor.id,
                                  actor_slack_id=actor_slack_id, reason=proposal.reason_code)
            await transition_case(session, case.id, CaseState.CLOSED, actor_user_id=actor.id,
                                  actor_slack_id=actor_slack_id)
            await set_case_lines_resolution(session, case.id, ResolutionStatus.RESOLVED, actor_user_id=actor.id,
                                            note=f"{proposal.reason_code}: {proposal.narrative}"[:2000])
            text = (f":white_check_mark: Resolved by <@{actor_slack_id}> as {proposal.reason_code}. "
                    "Status: *Resolved*.")
        else:
            await transition_case(session, case.id, CaseState.ASSIGNED, actor_user_id=actor.id,
                                  actor_slack_id=actor_slack_id)
            text = f"Proposal rejected by <@{actor_slack_id}>. Status stays *Pending*."

        await audit.record(
            session,
            workspace_id=workspace.id,
            action="PROPOSAL_DECIDED",
            actor_user_id=actor.id,
            actor_slack_id=actor_slack_id,
            case_id=case.id,
            reconciliation_id=case.reconciliation_id,
            to_state=str(proposal.state),
            detail={"proposal_id": str(proposal.id), "source": "slack_button"},
        )
        await _say(session, workspace, case, payload, text, key=f"decided:{proposal.id}")


async def _say(session: AsyncSession, workspace: Workspace, case: ExceptionCase, payload: dict, text: str, *, key: str) -> None:
    channel = case.slack_channel_id or payload.get("channel_id")
    if not channel:
        return
    await dispatcher.enqueue(
        session,
        workspace_id=workspace.id,
        channel_id=channel,
        thread_ts=case.slack_thread_ts,
        builder="case_decision",
        message={"text": text},
        case_id=case.id,
        idempotency_key=f"case-decision:{key}",
    )
