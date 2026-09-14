"""The agent decides which team owns each exception in a run (LLM call site L6).

Matching and exception typing stay deterministic; only the choice of owning team is the
model's. A decision the code cannot trust (no model, an unknown team, LOW confidence, no
reason) falls back to the rule table, so every exception still reaches exactly one team.
A run without unresolved exceptions queues nothing, so no team hears about a clean run.
"""
import asyncio
import logging
import re
import uuid
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.domain.enums import CaseType
from app.domain.money import format_minor
from app.models.cases import CaseRecord, CaseTransaction, ExceptionCase
from app.models.core import BankTransaction, PaymentRecordRow, Reconciliation, Workspace
from app.services import audit
from app.services.cases.routing import CASE_ROUTES, TEAM_LABELS, TEAM_RESPONSIBILITIES, CaseRoute, channel_for_team
from app.services.cases.slack_threads import UNRESOLVED_STATES, enqueue_case_threads
from app.services.jobs import queue
from app.services.outbox import dispatcher

logger = logging.getLogger(__name__)

ROUTE_JOB = "route_cases"
BATCH_SIZE = 25
TRUSTED_CONFIDENCE = frozenset({"HIGH", "MEDIUM"})
MAX_LINES_PER_CASE = 5
_LONG_DIGITS = re.compile(r"\d{7,}")


def _unrouted(workspace_id: uuid.UUID, reconciliation_id: uuid.UUID):
    return (
        select(ExceptionCase)
        .where(
            ExceptionCase.workspace_id == workspace_id,
            ExceptionCase.reconciliation_id == reconciliation_id,
            ExceptionCase.state.in_([str(state) for state in UNRESOLVED_STATES]),
            ExceptionCase.slack_thread_ts.is_(None),
            ExceptionCase.routed_team.is_(None),
        )
        .order_by(ExceptionCase.created_at, ExceptionCase.id)
    )


async def enqueue_routing(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    reconciliation_id: uuid.UUID,
    notify_channel_id: str | None = None,
    notify_thread_ts: str | None = None,
) -> bool:
    """Queue the routing job for a run. Returns False, queueing nothing, when the run has no exceptions."""
    pending = await session.scalar(_unrouted(workspace_id, reconciliation_id).with_only_columns(ExceptionCase.id).limit(1))
    if pending is None:
        return False
    payload: dict[str, Any] = {"reconciliation_id": str(reconciliation_id)}
    if notify_channel_id and notify_thread_ts:
        payload.update(notify_channel_id=notify_channel_id, notify_thread_ts=notify_thread_ts)
    await queue.enqueue(
        session,
        kind=ROUTE_JOB,
        idempotency_key=f"route-cases:{reconciliation_id}",
        payload=payload,
        workspace_id=workspace_id,
    )
    return True


async def route_run_cases(job, *, sessionmaker=None, llm=None) -> Counter:
    """Decide each exception's team, record why, then post it to that team's channel."""
    reconciliation_id = uuid.UUID(str(job.payload["reconciliation_id"]))
    workspace_id = uuid.UUID(str(job.workspace_id))
    factory = sessionmaker or get_sessionmaker()

    # Read, then call the model with no transaction or row lock held.
    async with factory() as session:
        pending = (await session.execute(_unrouted(workspace_id, reconciliation_id))).scalars().all()
        refs = {case.id: f"C{number}" for number, case in enumerate(pending, 1)}
        facts = [await _facts(session, case, refs[case.id]) for case in pending]
    decisions = await _agent_decisions(facts, llm) if facts else {}

    teams: Counter = Counter()
    async with factory() as session, session.begin():
        workspace = await session.get(Workspace, workspace_id)
        reconciliation = await session.get(Reconciliation, reconciliation_id)
        if workspace is None or workspace.uninstalled_at or reconciliation is None:
            return teams
        cases = (await session.execute(_unrouted(workspace_id, reconciliation_id).with_for_update())).scalars().all()
        for case in cases:
            _apply(case, decisions.get(refs.get(case.id, "")))
            teams[case.routed_team] += 1
            await audit.record(
                session,
                workspace_id=workspace_id,
                reconciliation_id=reconciliation_id,
                case_id=case.id,
                action="CASE_ROUTED",
                detail={"team": case.routed_team, "routed_by": case.routed_by,
                        "confidence": case.routing_confidence},
            )
        await session.flush()
        await enqueue_case_threads(session, workspace_id=workspace_id, reconciliation_id=reconciliation_id)

        channel, thread_ts = job.payload.get("notify_channel_id"), job.payload.get("notify_thread_ts")
        if teams and channel and thread_ts:
            parts = [
                f"<#{channel_for_team(team, workspace.case_channels, workspace.recon_channel_id)}> ({count})"
                for team, count in sorted(teams.items())
            ]
            total = sum(teams.values())
            await dispatcher.enqueue(
                session,
                workspace_id=workspace_id,
                channel_id=channel,
                thread_ts=thread_ts,
                builder="routing_summary",
                message={"text": f"{reconciliation.currency}: routed {total} exception(s) to "
                                 f"{' · '.join(parts)}. Teams with no exceptions were not notified."},
                idempotency_key=f"route-summary:{reconciliation_id}",
            )
    logger.info("cases_routed", extra={"component": "routing", "outcome": dict(teams)})
    return teams


async def _agent_decisions(facts: list[dict], llm) -> dict[str, dict]:
    if llm is None:
        from app.services.llm.client import LLMClient

        llm = LLMClient()
    if not getattr(llm, "available", False):
        return {}
    teams = {str(team): text for team, text in TEAM_RESPONSIBILITIES.items()}
    decisions: dict[str, dict] = {}
    for start in range(0, len(facts), BATCH_SIZE):
        batch = facts[start:start + BATCH_SIZE]
        refs = {fact["case_ref"] for fact in batch}
        for decision in await asyncio.to_thread(llm.route_cases, batch, teams) or []:
            if decision.get("case_ref") in refs:
                decisions[decision["case_ref"]] = decision
    return decisions


def _apply(case: ExceptionCase, decision: dict | None) -> None:
    decision = decision or {}
    team, confidence = decision.get("team"), decision.get("confidence")
    reason = " ".join(str(decision.get("reason") or "").split())[:300]
    if team in set(CaseRoute) and confidence in TRUSTED_CONFIDENCE and reason:
        case.routed_team, case.routed_by = str(team), "agent"
        case.routing_confidence, case.routing_reason = str(confidence), reason
        return
    rule_team = CASE_ROUTES[CaseType(case.type)]
    kind = str(case.type).replace("_", " ").lower()
    why = "the agent was not confident enough to decide" if decision else "the agent was unavailable"
    case.routed_team, case.routed_by = str(rule_team), "rule"
    case.routing_confidence = str(confidence) if confidence else None
    case.routing_reason = f"{TEAM_LABELS[rule_team]} owns {kind} cases; {why}."


def _mask(text: str | None) -> str:
    """Long digit runs (account numbers) never reach the model in full."""
    return _LONG_DIGITS.sub(lambda m: "*" * (len(m.group()) - 4) + m.group()[-4:], text or "")


async def _facts(session: AsyncSession, case: ExceptionCase, ref: str) -> dict[str, Any]:
    txns = (await session.execute(
        select(BankTransaction)
        .join(CaseTransaction, CaseTransaction.bank_transaction_id == BankTransaction.id)
        .where(CaseTransaction.case_id == case.id)
        .order_by(BankTransaction.row_index)
        .limit(MAX_LINES_PER_CASE)
    )).scalars().all()
    records = (await session.execute(
        select(PaymentRecordRow)
        .join(CaseRecord, CaseRecord.payment_record_id == PaymentRecordRow.id)
        .where(CaseRecord.case_id == case.id)
        .order_by(PaymentRecordRow.record_date)
        .limit(MAX_LINES_PER_CASE)
    )).scalars().all()
    return {
        "case_ref": ref,
        "rule_label": str(case.type),
        "title": _mask(case.title[:160]),
        "summary": _mask(case.summary[:400]),
        "value_at_risk": format_minor(case.value_at_risk_minor, case.currency),
        "bank_lines": [
            {"date": t.value_date.isoformat(), "direction": str(t.direction),
             "amount": format_minor(t.amount_minor, t.currency), "description": _mask(t.narration[:160]),
             "counterparty": _mask(t.counterparty_norm[:80]), "reference": _mask(t.reference_norm[:40])}
            for t in txns
        ],
        "ledger_records": [
            {"date": r.record_date.isoformat(), "direction": str(r.direction),
             "amount": format_minor(r.amount_minor, r.currency),
             "counterparty": _mask(r.counterparty_norm[:80]), "reference": _mask(r.reference_norm[:40])}
            for r in records
        ],
    }
