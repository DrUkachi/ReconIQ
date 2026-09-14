"""Routed case threads, Slack comments as evidence, one-click confirmation, and web sign-in into Slack."""
import os
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.enums import CaseState, ProposalState, ResolutionStatus, Role, TransactionStatus
from app.models.cases import CaseEvidence, CaseTransaction, ExceptionCase, ResolutionProposal
from app.models.core import AppUser, BankTransaction, Workspace
from app.models.infra import SlackOutbox
from app.services.cases.comments import handle_case_comment
from app.services.cases.interactions import handle_interaction
from app.services.cases.routing import channel_for
from app.services.cases.slack_threads import CASE_THREAD_BUILDER, enqueue_case_threads
from app.services.ingestion.persistence import import_signed_sources
from app.services.matching.persistence import match_reconciliation
from app.services.outbox import dispatcher
from app.services.slack.intake import parse_file
from app.services.web_auth import ensure_web_identity

FIXTURES = Path(__file__).parent / "fixtures" / "signed_exports"
URL = os.environ.get("RECONIQ_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="RECONIQ_TEST_DATABASE_URL is not set")

CHANNELS = {"accounts": "C_ACCOUNTS", "payments": "C_PAYMENTS", "treasury": "C_TREASURY"}


class FakeSlack:
    def __init__(self):
        self.posts = []

    async def chat_postMessage(self, **kwargs):
        self.posts.append(kwargs)
        return {"ts": f"{1700000000 + len(self.posts)}.000100"}

    async def chat_getPermalink(self, **kwargs):
        return {"permalink": f"https://slack.test/{kwargs['message_ts']}"}


class FakeLLM:
    def __init__(self, result):
        self.result, self.calls = result, []

    def parse_reply_intent(self, text, context=""):
        self.calls.append((text, context))
        return self.result


SETTLED = {"intent": "PROPOSE_RESOLUTION", "reason_code": "PAID_LATE", "assignee": None, "confidence": "HIGH"}
UNSETTLED = {"intent": "PROVIDE_EVIDENCE", "reason_code": None, "assignee": None, "confidence": "MEDIUM"}


@pytest_asyncio.fixture
async def recon_db():
    engine = create_async_engine(URL)
    async with engine.connect() as conn:
        outer = await conn.begin()
        factory = async_sessionmaker(conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        async with factory() as session, session.begin():
            workspace = Workspace(slack_team_id=f"TEST_{uuid.uuid4().hex[:20]}", name="Case workflow test",
                                  bot_token="fake", bot_user_id="U_BOT", recon_channel_id="C_RECON",
                                  case_channels=CHANNELS)
            session.add(workspace)
            await session.flush()
            owner = AppUser(workspace_id=workspace.id, slack_user_id="U_OWNER", role=Role.OWNER)
            session.add(owner)
            await session.flush()
            bank = parse_file((FIXTURES / "Bank_Statement_Demo.pdf").read_bytes(), "Bank_Statement_Demo.pdf", "bank")
            ledger = parse_file((FIXTURES / "General_Ledger_Demo.csv").read_bytes(), "General_Ledger_Demo.csv", "ledger")
            ids = await import_signed_sources(
                session, workspace_id=workspace.id, actor_user_id=owner.id, account_last4="DEMO",
                start=date(2026, 8, 1), end=date(2026, 8, 31), bank=bank, ledger=ledger, channel_id="C_RECON")
            for rid in ids:
                await match_reconciliation(session, workspace_id=workspace.id, reconciliation_id=rid)
        yield factory, workspace, ids
        await outer.rollback()
    await engine.dispose()


def reply(workspace, case, text, *, user="U_OWNER", ts="1800000000.000200"):
    return SimpleNamespace(id=uuid.uuid4(), workspace_id=workspace.id, payload={
        "team_id": workspace.slack_team_id,
        "event": {"type": "message", "channel": case.slack_channel_id, "thread_ts": case.slack_thread_ts,
                  "ts": ts, "user": user, "text": text}})


def click(workspace, proposal_id, *, handler="apply_resolution", user="U_OWNER", channel="C_TREASURY"):
    return SimpleNamespace(id=uuid.uuid4(), workspace_id=workspace.id, payload={
        "handler": handler, "value": str(proposal_id), "actor_slack_id": user,
        "channel_id": channel, "message_ts": "1800000000.000900", "team_id": workspace.slack_team_id})


async def post_all_threads(factory, workspace):
    slack = FakeSlack()
    async with factory() as session, session.begin():
        queued = await enqueue_case_threads(session, workspace_id=workspace.id)
    async with factory() as session:
        while await dispatcher.dispatch_once(session, slack):
            # The dispatcher paces each channel at about one post a second; age the sends instead of sleeping.
            await session.execute(update(SlackOutbox).where(SlackOutbox.sent_at.is_not(None))
                                  .values(sent_at=SlackOutbox.sent_at - timedelta(seconds=5)))
            await session.commit()
    return queued, slack


async def threaded_case(factory, workspace):
    async with factory() as session:
        return await session.scalar(select(ExceptionCase).where(
            ExceptionCase.workspace_id == workspace.id, ExceptionCase.slack_thread_ts.is_not(None),
        ).order_by(ExceptionCase.created_at, ExceptionCase.id).limit(1))


@pytest.mark.asyncio
async def test_every_line_is_matched_or_owned_by_a_case_and_auto_matches_start_resolved(recon_db):
    factory, workspace, ids = recon_db
    async with factory() as session:
        orphans = await session.scalar(select(func.count()).select_from(BankTransaction).where(
            BankTransaction.reconciliation_id.in_(ids), BankTransaction.status == TransactionStatus.UNMATCHED,
            ~exists().where(CaseTransaction.bank_transaction_id == BankTransaction.id)))
        auto = (await session.execute(select(BankTransaction.resolution_status).where(
            BankTransaction.reconciliation_id.in_(ids), BankTransaction.status == TransactionStatus.AUTO))).scalars().all()
        in_case = (await session.execute(select(BankTransaction.resolution_status).where(
            BankTransaction.reconciliation_id.in_(ids), BankTransaction.status == TransactionStatus.IN_CASE))).scalars().all()
    assert orphans == 0
    assert auto and set(auto) == {ResolutionStatus.RESOLVED}
    assert in_case and set(in_case) == {ResolutionStatus.PENDING}


@pytest.mark.asyncio
async def test_unresolved_cases_are_posted_once_to_their_team_channel_and_threads_recorded(recon_db):
    factory, workspace, _ = recon_db
    queued, slack = await post_all_threads(factory, workspace)
    async with factory() as session:
        cases = (await session.execute(select(ExceptionCase).where(ExceptionCase.workspace_id == workspace.id))).scalars().all()
        again = await enqueue_case_threads(session, workspace_id=workspace.id)
    assert queued == len(cases) == len(slack.posts) > 0
    assert again == 0
    for case in cases:
        assert case.slack_channel_id == channel_for(case.type, CHANNELS, "C_RECON")
        assert case.slack_thread_ts and case.permalink
    assert {post["channel"] for post in slack.posts} <= set(CHANNELS.values())
    assert all(post["thread_ts"] is None for post in slack.posts)


@pytest.mark.asyncio
async def test_a_settling_comment_becomes_a_proposal_and_one_click_resolves_the_lines(recon_db):
    factory, workspace, _ = recon_db
    await post_all_threads(factory, workspace)
    case = await threaded_case(factory, workspace)
    llm = FakeLLM(SETTLED)

    assert await handle_case_comment(reply(workspace, case, "Paid late on 4 Sep, ref TRX-991"), sessionmaker=factory, llm=llm)
    # Slack retries the same event: recorded once, no second model call.
    assert await handle_case_comment(reply(workspace, case, "Paid late on 4 Sep, ref TRX-991"), sessionmaker=factory, llm=llm)
    assert len(llm.calls) == 1

    async with factory() as session:
        refreshed = await session.get(ExceptionCase, case.id)
        proposal = await session.scalar(select(ResolutionProposal).where(ResolutionProposal.case_id == case.id))
        evidence = (await session.execute(select(CaseEvidence).where(CaseEvidence.case_id == case.id))).scalars().all()
        approval = await session.scalar(select(SlackOutbox).where(SlackOutbox.idempotency_key == f"proposal:{proposal.id}"))
    assert refreshed.state == CaseState.PROPOSED
    assert proposal.state == ProposalState.PENDING and proposal.reason_code == "PAID_LATE"
    assert len(evidence) == 1 and evidence[0].verified is False
    assert approval.thread_ts == case.slack_thread_ts
    assert {e["action_id"] for b in approval.blocks if b["type"] == "actions" for e in b["elements"]} == {"proposal_approve", "proposal_reject"}

    await handle_interaction(click(workspace, proposal.id, channel=case.slack_channel_id), sessionmaker=factory)
    async with factory() as session:
        closed = await session.get(ExceptionCase, case.id, populate_existing=True)
        decided = await session.get(ResolutionProposal, proposal.id, populate_existing=True)
        lines = (await session.execute(select(BankTransaction).join(
            CaseTransaction, CaseTransaction.bank_transaction_id == BankTransaction.id).where(
            CaseTransaction.case_id == case.id).execution_options(populate_existing=True))).scalars().all()
    assert closed.state == CaseState.CLOSED
    assert decided.state == ProposalState.APPROVED
    assert lines and {line.resolution_status for line in lines} == {ResolutionStatus.RESOLVED}
    assert all(line.resolution_note.startswith("PAID_LATE") for line in lines)


@pytest.mark.asyncio
async def test_a_non_settling_comment_is_evidence_and_the_case_stays_pending(recon_db):
    factory, workspace, _ = recon_db
    await post_all_threads(factory, workspace)
    case = await threaded_case(factory, workspace)

    assert await handle_case_comment(reply(workspace, case, "Checking with the bank"), sessionmaker=factory, llm=FakeLLM(UNSETTLED))
    async with factory() as session:
        refreshed = await session.get(ExceptionCase, case.id)
        proposals = await session.scalar(select(func.count()).select_from(ResolutionProposal).where(ResolutionProposal.case_id == case.id))
        ack = await session.scalar(select(SlackOutbox).where(SlackOutbox.builder == "case_comment_ack", SlackOutbox.case_id == case.id))
    assert refreshed.state == case.state and proposals == 0
    assert "Pending" in ack.fallback_text


@pytest.mark.asyncio
async def test_a_member_cannot_confirm_an_unassigned_case_and_nothing_changes(recon_db):
    factory, workspace, _ = recon_db
    await post_all_threads(factory, workspace)
    case = await threaded_case(factory, workspace)
    await handle_case_comment(reply(workspace, case, "Paid late on 4 Sep"), sessionmaker=factory, llm=FakeLLM(SETTLED))
    async with factory() as session:
        proposal = await session.scalar(select(ResolutionProposal).where(ResolutionProposal.case_id == case.id))

    await handle_interaction(click(workspace, proposal.id, user="U_STRANGER", channel=case.slack_channel_id), sessionmaker=factory)
    async with factory() as session:
        still = await session.get(ResolutionProposal, proposal.id, populate_existing=True)
        refused = await session.scalar(select(SlackOutbox).where(SlackOutbox.idempotency_key.like("case-decision:denied:%")))
    assert still.state == ProposalState.PENDING
    assert refused is not None


@pytest.mark.asyncio
async def test_non_case_threads_are_left_to_other_handlers(recon_db):
    factory, workspace, _ = recon_db
    stray = SimpleNamespace(slack_channel_id="C_ELSEWHERE", slack_thread_ts="1.1")
    assert not await handle_case_comment(reply(workspace, stray, "hello"), sessionmaker=factory, llm=FakeLLM(SETTLED))


@pytest.mark.asyncio
async def test_web_sign_in_joins_the_slack_workspace_for_a_member_email(recon_db):
    factory, workspace, _ = recon_db

    async def lookup(session, email):
        return (await session.get(Workspace, workspace.id), "U_OWNER", "Owner Person") if email == "owner@example.com" else None

    async with factory() as session, session.begin():
        joined, user = await ensure_web_identity(session, email="Owner@Example.com", slack_lookup=lookup)
        other, stranger = await ensure_web_identity(session, email="stranger@example.com", slack_lookup=lookup)
    assert joined.id == workspace.id and user.slack_user_id == "U_OWNER" and user.role == Role.OWNER
    assert other.id != workspace.id and stranger.role == Role.OWNER


async def list_page(session, workspace_id, **overrides):
    from app.api.v1.routes.transactions import list_all_transactions

    params = dict(page=1, page_size=10, resolution_status=None, status=None, currency=None,
                  reconciliation_id=None, q=None)
    params.update(overrides)
    return await list_all_transactions(session=session, principal=SimpleNamespace(workspace_id=workspace_id), **params)


@pytest.mark.asyncio
async def test_workspace_transaction_list_pages_through_every_line_with_filters_and_cases(recon_db):
    factory, workspace, ids = recon_db
    async with factory() as session:
        total = await session.scalar(select(func.count()).select_from(BankTransaction).where(
            BankTransaction.reconciliation_id.in_(ids)))
        first = await list_page(session, workspace.id)
        seen = [item.id for item in first.items]
        for number in range(2, first.pages + 1):
            seen += [item.id for item in (await list_page(session, workspace.id, page=number)).items]
        beyond = await list_page(session, workspace.id, page=999)
        pending = await list_page(session, workspace.id, page_size=100, resolution_status=ResolutionStatus.PENDING)
        resolved = await list_page(session, workspace.id, page_size=100, resolution_status=ResolutionStatus.RESOLVED)
        in_case = await list_page(session, workspace.id, page_size=100, status=TransactionStatus.IN_CASE)
        usd = await list_page(session, workspace.id, page_size=100, currency="usd")
        other_workspace = await list_page(session, uuid.uuid4())

    assert first.total == total and len(first.items) == 10 and first.pages == -(-total // 10)
    assert len(seen) == len(set(seen)) == total
    assert beyond.page == first.pages and beyond.items
    assert pending.total + resolved.total == total
    assert pending.resolution_counts == first.resolution_counts
    assert {i.resolution_status for i in pending.items} == {ResolutionStatus.PENDING}
    assert in_case.items and all(i.case_id and i.case_type for i in in_case.items)
    assert usd.items and {i.currency for i in usd.items} == {"USD"}
    assert first.currencies == sorted(first.currencies) and "USD" in first.currencies
    assert other_workspace.total == 0 and other_workspace.items == []


class FakeRouter:
    available = True

    def __init__(self, decide):
        self.decide, self.calls = decide, []

    def route_cases(self, cases, teams):
        self.calls.append((cases, teams))
        return [self.decide(case) for case in cases]


def route_job(workspace, rid, *, notify=True):
    from app.services.cases.team_routing import ROUTE_JOB

    payload = {"reconciliation_id": str(rid)}
    if notify:
        payload.update(notify_channel_id="C_INTAKE", notify_thread_ts="1700000000.000100")
    return SimpleNamespace(id=uuid.uuid4(), kind=ROUTE_JOB, workspace_id=workspace.id, payload=payload)


async def case_counts(factory, ids):
    async with factory() as session:
        rows = dict((await session.execute(select(ExceptionCase.reconciliation_id, func.count()).where(
            ExceptionCase.reconciliation_id.in_(ids)).group_by(ExceptionCase.reconciliation_id))).all())
    return {rid: rows.get(rid, 0) for rid in ids}


@pytest.mark.asyncio
async def test_a_run_without_exceptions_notifies_no_team(recon_db):
    from app.models.infra import Job
    from app.services.cases.team_routing import enqueue_routing, route_run_cases

    factory, workspace, ids = recon_db
    clean = [rid for rid, count in (await case_counts(factory, ids)).items() if count == 0]
    assert clean, "the demo fixture has a currency run with no exceptions"
    router = FakeRouter(lambda case: {})
    async with factory() as session, session.begin():
        assert await enqueue_routing(session, workspace_id=workspace.id, reconciliation_id=clean[0],
                                     notify_channel_id="C_INTAKE", notify_thread_ts="1.0") is False
        jobs = await session.scalar(select(func.count()).select_from(Job).where(Job.idempotency_key == f"route-cases:{clean[0]}"))
    assert jobs == 0
    assert not await route_run_cases(route_job(workspace, clean[0]), sessionmaker=factory, llm=router)
    async with factory() as session:
        posts = await session.scalar(select(func.count()).select_from(SlackOutbox).where(SlackOutbox.workspace_id == workspace.id))
    assert posts == 0 and router.calls == []


@pytest.mark.asyncio
async def test_the_agent_decides_each_team_and_untrusted_decisions_fall_back_to_rules(recon_db):
    from app.domain.enums import CaseType
    from app.models.infra import AuditEvent, Job
    from app.services.cases.routing import CASE_ROUTES
    from app.services.cases.team_routing import enqueue_routing, route_run_cases

    factory, workspace, ids = recon_db
    busiest = max((await case_counts(factory, ids)).items(), key=lambda item: item[1])[0]
    async with factory() as session, session.begin():
        assert await enqueue_routing(session, workspace_id=workspace.id, reconciliation_id=busiest,
                                     notify_channel_id="C_INTAKE", notify_thread_ts="1700000000.000100")
        assert await session.scalar(select(Job.kind).where(Job.idempotency_key == f"route-cases:{busiest}")) == "route_cases"

    def decide(case):
        if case["case_ref"] == "C1":
            return {"case_ref": "C1", "team": "treasury", "confidence": "LOW", "reason": "Not sure."}
        if case["case_ref"] == "C2":
            return {"case_ref": "C2", "team": "marketing", "confidence": "HIGH", "reason": "Invented team."}
        return {"case_ref": case["case_ref"], "team": "treasury", "confidence": "HIGH",
                "reason": "Bank-side item <!channel> for the bank relationship team."}

    router = FakeRouter(decide)
    teams = await route_run_cases(route_job(workspace, busiest), sessionmaker=factory, llm=router)

    async with factory() as session:
        cases = (await session.execute(select(ExceptionCase).where(ExceptionCase.reconciliation_id == busiest)
                                       .order_by(ExceptionCase.created_at, ExceptionCase.id))).scalars().all()
        openers = {row.case_id: row for row in (await session.execute(select(SlackOutbox).where(
            SlackOutbox.builder == CASE_THREAD_BUILDER, SlackOutbox.case_id.in_([c.id for c in cases])))).scalars()}
        summary = await session.scalar(select(SlackOutbox).where(SlackOutbox.idempotency_key == f"route-summary:{busiest}"))
        routed_audits = await session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.reconciliation_id == busiest, AuditEvent.action == "CASE_ROUTED"))

    sent_cases, sent_teams = router.calls[0]
    assert set(sent_teams) == set(CHANNELS)
    assert {"case_ref", "rule_label", "bank_lines", "ledger_records"} <= set(sent_cases[0])
    assert len(cases) >= 3 and sum(teams.values()) == len(cases) == len(openers) == routed_audits

    for case in cases[:2]:
        rule_team = str(CASE_ROUTES[CaseType(case.type)])
        assert (case.routed_by, case.routed_team) == ("rule", rule_team)
        assert openers[case.id].channel_id == CHANNELS[rule_team]
    for case in cases[2:]:
        assert (case.routed_by, case.routed_team, case.routing_confidence) == ("agent", "treasury", "HIGH")
        assert openers[case.id].channel_id == CHANNELS["treasury"]
        text = str(openers[case.id].blocks)
        assert "Routed to *Treasury* by ReconIQ" in text and "&lt;!channel&gt;" in text and "<!channel>" not in text

    assert (summary.channel_id, summary.thread_ts) == ("C_INTAKE", "1700000000.000100")
    assert "<#C_TREASURY>" in summary.fallback_text and "not notified" in summary.fallback_text

    # Large runs are decided in batches, one model call each.
    from app.services.cases.team_routing import BATCH_SIZE

    calls = len(router.calls)
    assert calls == -(-len(cases) // BATCH_SIZE)
    assert all(len(batch) <= BATCH_SIZE for batch, _ in router.calls)

    # A replayed job finds nothing left to route: no further model call and no second post.
    assert not await route_run_cases(route_job(workspace, busiest), sessionmaker=factory, llm=router)
    async with factory() as session:
        again = await session.scalar(select(func.count()).select_from(SlackOutbox).where(
            SlackOutbox.builder == CASE_THREAD_BUILDER, SlackOutbox.case_id.in_([c.id for c in cases])))
    assert len(router.calls) == calls and again == len(cases)


@pytest.mark.asyncio
async def test_every_exception_is_still_delivered_when_the_agent_is_unavailable(recon_db):
    from app.services.cases.team_routing import route_run_cases

    factory, workspace, ids = recon_db
    busiest = max((await case_counts(factory, ids)).items(), key=lambda item: item[1])[0]
    teams = await route_run_cases(route_job(workspace, busiest, notify=False), sessionmaker=factory,
                                  llm=SimpleNamespace(available=False))
    async with factory() as session:
        cases = (await session.execute(select(ExceptionCase).where(ExceptionCase.reconciliation_id == busiest))).scalars().all()
        openers = await session.scalar(select(func.count()).select_from(SlackOutbox).where(
            SlackOutbox.builder == CASE_THREAD_BUILDER, SlackOutbox.case_id.in_([c.id for c in cases])))
    assert sum(teams.values()) == len(cases) == openers
    assert {c.routed_by for c in cases} == {"rule"}
    assert all("agent was unavailable" in c.routing_reason for c in cases)
