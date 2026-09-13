"""Team replies in a case thread become evidence; settling replies become proposals.

The agent never resolves a case here. It proposes, and only a verified button click by an
authorised person applies the resolution (see interactions.py, PRD rule T1).
"""
import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.domain.enums import CaseState, EvidenceKind, ProposalState, ResolutionReasonCode, Role
from app.models.cases import CaseEvidence, ExceptionCase, ResolutionProposal
from app.models.core import AppUser, Workspace
from app.services import audit
from app.services.cases.slack_threads import escape
from app.services.cases.transitions import transition_case
from app.services.llm.schemas import Confidence, ReplyIntent
from app.services.outbox import dispatcher
from app.services.slack.blocks import build_approval_request

RESOLVED_STATES = {CaseState.RESOLVED, CaseState.CLOSED}
REASON_CODES = {str(code) for code in ResolutionReasonCode}
SETTLING_CONFIDENCE = {str(Confidence.HIGH), str(Confidence.MEDIUM)}


async def slack_actor(session: AsyncSession, workspace_id: uuid.UUID, slack_user_id: str) -> AppUser:
    """The app user behind a Slack-signed event; unknown members start with the member role."""
    actor = await session.scalar(
        select(AppUser).where(AppUser.workspace_id == workspace_id, AppUser.slack_user_id == slack_user_id)
    )
    if actor is None:
        actor = AppUser(workspace_id=workspace_id, slack_user_id=slack_user_id, role=Role.MEMBER)
        session.add(actor)
        await session.flush()
    return actor


async def handle_case_comment(job, *, sessionmaker=None, llm=None) -> bool:
    """Returns False when the reply is not in a case thread."""
    event = job.payload.get("event") or {}
    channel, thread_ts, user = event.get("channel"), event.get("thread_ts"), event.get("user")
    message_ts, text = event.get("ts"), (event.get("text") or "").strip()
    if not channel or not thread_ts or not user or not message_ts or event.get("bot_id"):
        return False

    factory = sessionmaker or get_sessionmaker()
    async with factory() as session, session.begin():
        workspace = await session.get(Workspace, job.workspace_id)
        if workspace is None or workspace.uninstalled_at or user == workspace.bot_user_id:
            return False
        case = await session.scalar(
            select(ExceptionCase)
            .where(
                ExceptionCase.workspace_id == workspace.id,
                ExceptionCase.slack_channel_id == channel,
                ExceptionCase.slack_thread_ts == thread_ts,
            )
            .with_for_update()
        )
        if case is None:
            return False
        if not text:
            return True

        marker = f"slack:{channel}:{message_ts}"
        already = await session.scalar(
            select(CaseEvidence.id).where(CaseEvidence.case_id == case.id, CaseEvidence.matched_on.contains([marker]))
        )
        if already:
            return True

        actor = await slack_actor(session, workspace.id, user)
        evidence = CaseEvidence(
            case_id=case.id,
            kind=EvidenceKind.THREAD_REPLY,
            author_slack_id=user,
            excerpt=text[:2000],
            matched_on=[marker],
            verified=False,
            added_by=actor.id,
        )
        session.add(evidence)
        await session.flush()
        await audit.record(
            session,
            workspace_id=workspace.id,
            actor_user_id=actor.id,
            actor_slack_id=user,
            reconciliation_id=case.reconciliation_id,
            case_id=case.id,
            action="EVIDENCE_ADDED",
            detail={"source": "slack_thread", "message_ts": message_ts},
        )

        state = CaseState(case.state)
        if state in RESOLVED_STATES:
            await _reply(session, workspace, case, message_ts,
                         "Noted. This case is already resolved; your comment is saved on its record.")
            return True
        if await session.scalar(select(ResolutionProposal.id).where(
            ResolutionProposal.case_id == case.id, ResolutionProposal.state == ProposalState.PENDING,
        )):
            await _reply(session, workspace, case, message_ts,
                         "Noted as evidence. A proposed resolution is already waiting for confirmation in this thread.")
            return True

        if llm is None:
            from app.services.llm.client import LLMClient

            llm = LLMClient()
        intent = await asyncio.to_thread(
            llm.parse_reply_intent, text, f"{case.type}: {case.title}. {case.summary}"
        )
        reason = intent.get("reason_code")
        settles = (
            intent.get("intent") == ReplyIntent.PROPOSE_RESOLUTION
            and intent.get("confidence") in SETTLING_CONFIDENCE
            and reason in REASON_CODES
        )
        if not settles:
            await _reply(session, workspace, case, message_ts,
                         "Recorded as evidence. Status stays *Pending*. When it is settled, say how "
                         "(for example “paid late on 4 Sep, ref …”) and I will propose a resolution.")
            return True

        if case.assignee_id is None:
            case.assignee_id = actor.id
            await session.flush()
        if state is CaseState.PROPOSED:
            await transition_case(session, case.id, CaseState.ASSIGNED, actor_user_id=actor.id, actor_slack_id=user)
        elif state in (CaseState.OPEN, CaseState.REOPENED):
            await transition_case(session, case.id, CaseState.ASSIGNED, actor_user_id=actor.id, actor_slack_id=user)

        proposal = ResolutionProposal(
            case_id=case.id,
            reason_code=reason,
            narrative=text[:2000],
            evidence_ids=[str(evidence.id)],
            state=ProposalState.PENDING,
            proposed_by=actor.id,
            case_version=case.version,
        )
        session.add(proposal)
        await session.flush()
        await transition_case(session, case.id, CaseState.PROPOSED, actor_user_id=actor.id, actor_slack_id=user)

        message = build_approval_request(
            proposal_id=str(proposal.id),
            case_title=escape(case.title),
            reason_code=reason,
            narrative=f"<@{user}>: {escape(text[:1500])}",
            value_at_risk_minor=case.value_at_risk_minor,
            evidence_count=1,
            requires_approver=case.value_at_risk_minor >= workspace.approval_value_threshold_minor,
            currency=case.currency,
        )
        await dispatcher.enqueue(
            session,
            workspace_id=workspace.id,
            channel_id=channel,
            thread_ts=thread_ts,
            builder="approval_request",
            message=message,
            case_id=case.id,
            idempotency_key=f"proposal:{proposal.id}",
        )
        return True


async def _reply(session: AsyncSession, workspace: Workspace, case: ExceptionCase, message_ts: str, text: str) -> None:
    await dispatcher.enqueue(
        session,
        workspace_id=workspace.id,
        channel_id=case.slack_channel_id,
        thread_ts=case.slack_thread_ts,
        builder="case_comment_ack",
        message={"text": text},
        case_id=case.id,
        idempotency_key=f"case-comment:{case.id}:{message_ts}",
    )
