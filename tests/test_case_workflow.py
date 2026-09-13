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
