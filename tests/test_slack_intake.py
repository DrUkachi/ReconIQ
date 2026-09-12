import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from slack_sdk.errors import SlackApiError
from slack_sdk.web.slack_response import SlackResponse
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.errors import BankReconError
from app.domain.enums import Role
from app.models import AppUser, Workspace, Reconciliation, BankTransaction, PaymentRecordRow
from app.models.base import utcnow
from app.models.infra import Job, SlackOutbox
from app.models.slack_intake import SlackIntake, SlackIntakeFile
from app.services.slack.client import download_file, validate_file_url
from app.services.slack.intake import handle_intake_event, process_intake
from app.services.slack.intake_rules import parse_context, file_role
from app.services.outbox import dispatcher

FIXTURES = Path(__file__).parent / "fixtures" / "signed_exports"
URL = os.environ.get("RECONIQ_TEST_DATABASE_URL")
db_test = pytest.mark.skipif(not URL, reason="RECONIQ_TEST_DATABASE_URL is not set")


@pytest.mark.parametrize("text,start,end,account", [
    ("reconcile August 2026 account 1234", date(2026,8,1), date(2026,8,31), "1234"),
    ("2024-02 account DEMO", date(2024,2,1), date(2024,2,29), "DEMO"),
    ("2026-08-02 to 2026-08-17", date(2026,8,2), date(2026,8,17), None),
    ("account ending 0023", None, None, "0023"),
])
def test_context(text, start, end, account):
    result = parse_context(text)
    assert (result.start, result.end, result.account, result.error) == (start,end,account,"")


@pytest.mark.parametrize("text", ["2026-13", "2026-08-20 to 2026-08-01", "August 2026 September 2026", "account 1234 account 5678"])
def test_ambiguous_or_invalid_context(text):
    assert parse_context(text).error


@pytest.mark.parametrize("name,role", [("Bank_Statement_Demo.pdf","bank"), ("General_Ledger_Demo.csv","ledger"), ("Reconciliation_Demo_Guide.pdf","context"), ("Ingestion_Edge_Cases_Demo.pdf","validation"), ("payload.exe","unsupported")])
def test_roles(name,role):
    assert file_role(name, "") == role


@pytest.mark.parametrize("url", ["http://files.slack.com/f", "https://files.slack.com.evil.test/f", "https://evil.test/f", "https://user:password@files.slack.com/f", "https://files.slack.com:8080/f", "file:///etc/passwd"])
def test_file_hosts(url):
    with pytest.raises(BankReconError):
        validate_file_url(url)


@pytest.mark.asyncio
async def test_redirect_never_sends_token_to_another_host():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location":"https://evil.test/file"})
    with pytest.raises(BankReconError):
        await download_file({"url_private":"https://files.slack.com/f"}, "test-token", 100, transport=httpx.MockTransport(handler))
    assert len(requests) == 1
    assert requests[0].url.host == "files.slack.com"


@pytest.mark.asyncio
async def test_actual_size_limit_even_if_metadata_lies():
    with pytest.raises(BankReconError):
        await download_file({"size":1,"url_private":"https://files.slack.com/f"}, "test-token", 4,
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"12345")))


@pytest.mark.asyncio
async def test_invalid_size_metadata_is_a_validation_error():
    with pytest.raises(BankReconError):
        await download_file({"size":"invalid"}, "fake", 100)


class FakeSlack:
    def __init__(self):
        self.files = {"FB": "Bank_Statement_Demo.pdf", "FL": "General_Ledger_Demo.csv", "FE": "Ingestion_Edge_Cases_Demo.pdf", "FG": "Reconciliation_Demo_Guide.pdf"}
        self.reads, self.posts = [], []
        self.failure = None

    async def files_info(self, *, file):
        self.reads.append(file)
        return {"file": {"id": file, "name": self.files[file], "url_private": f"https://files.slack.com/{file}", "shares":{"public":{"C_TEST":[{"ts":"1.0"}]}}}}

    def download(self, request):
        return httpx.Response(200, content=(FIXTURES / self.files[request.url.path[1:]]).read_bytes())

    async def chat_postMessage(self, **kwargs):
        self.posts.append(kwargs)
        if self.failure:
            raise self.failure
        return {"ts": "999.0"}

    async def chat_getPermalink(self, **kwargs):
        raise RuntimeError("permalink unavailable after accepted post")


@pytest_asyncio.fixture
async def intake_db():
    engine = create_async_engine(URL)
    async with engine.connect() as conn:
        outer = await conn.begin()
        factory = async_sessionmaker(conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        async with factory() as session, session.begin():
            workspace = Workspace(slack_team_id=f"TEST_{uuid.uuid4().hex[:20]}", name="Slack intake test", bot_token="fake", bot_user_id="U_BOT", recon_channel_id="C_TEST")
            session.add(workspace)
            await session.flush()
            session.add(AppUser(workspace_id=workspace.id, slack_user_id="U_OWNER", role=Role.OWNER))
        yield factory, workspace, FakeSlack()
        await outer.rollback()
    await engine.dispose()


def event(workspace, text="", files=(), thread="1.0", user="U_OWNER", channel="C_TEST", **extra):
    return SimpleNamespace(id=uuid.uuid4(), workspace_id=workspace.id, payload={"team_id":workspace.slack_team_id,"event_id":str(uuid.uuid4()),
        "event":{"type":"message","ts":"2.0","thread_ts":thread,"user":user,"channel":channel,"text":text,
                 "files":[{"id":f} for f in files], **extra}})


async def send(db, text="", files=(), **kwargs):
    factory, workspace, client = db
    job = event(workspace, text, files, **kwargs)
    await handle_intake_event(job, sessionmaker=factory, client=client, transport=httpx.MockTransport(client.download))
    return job


@db_test
@pytest.mark.asyncio
@pytest.mark.parametrize("order", [("FB","FL"),("FL","FB")])
async def test_either_order_context_later_restart_and_replays(intake_db,order):
    factory, workspace, client = intake_db
    await send(intake_db, files=[order[0]])
    await send(intake_db, files=[order[1],"FE","FG"])
    async with factory() as session:
        intake = await session.scalar(select(SlackIntake).where(SlackIntake.workspace_id == workspace.id))
        assert intake.status == "WAITING"
        assert not intake.period_start
    await send(intake_db, "reconcile August 2026 account DEMO")
    async with factory() as session:
        job = await session.scalar(select(Job).where(Job.workspace_id == workspace.id,Job.kind == "process_intake"))
    await process_intake(job, sessionmaker=factory)
    await process_intake(job, sessionmaker=factory)
    await send(intake_db, files=[order[0]])
    async with factory() as session:
        intake = await session.scalar(select(SlackIntake).where(SlackIntake.workspace_id == workspace.id))
        assert intake.status == "PROCESSED"
        assert len(intake.reconciliation_ids) == 3
        ids = [uuid.UUID(rid) for rid in intake.reconciliation_ids]
        assert await session.scalar(select(func.count()).select_from(BankTransaction).where(BankTransaction.reconciliation_id.in_(ids))) == 55
        assert await session.scalar(select(func.count()).select_from(PaymentRecordRow).where(PaymentRecordRow.reconciliation_id.in_(ids))) == 52
        reports = list(await session.scalars(select(SlackIntakeFile).where(SlackIntakeFile.intake_id == intake.id)))
        validation = next(r for r in reports if r.role == "validation")
        assert (validation.report["accepted"], validation.report["rejected"]) == (5,11)
        summaries = list(await session.scalars(select(SlackOutbox).where(SlackOutbox.workspace_id == workspace.id,SlackOutbox.idempotency_key.like("%:summary:%"))))
        assert len(summaries) == 3
        assert all(r.thread_ts == "1.0" and "processing finished" in r.fallback_text for r in summaries)
        assert len(client.reads) == 4


@db_test
@pytest.mark.asyncio
async def test_unknown_member_cannot_download_and_other_channel_ignored(intake_db):
    factory, workspace, client = intake_db
    await send(intake_db, files=["FB"], user="U_UNKNOWN")
    await send(intake_db, files=["FB"], channel="C_OTHER")
    await send(intake_db, files=["FB"], user="U_BOT")
    assert not client.reads
    async with factory() as session:
        assert not await session.scalar(select(SlackIntake.id).where(SlackIntake.workspace_id == workspace.id))
        user = await session.scalar(select(AppUser).where(AppUser.workspace_id == workspace.id,AppUser.slack_user_id == "U_UNKNOWN"))
        assert user.role == Role.MEMBER


@db_test
@pytest.mark.asyncio
async def test_threads_never_pair_and_cancel_is_terminal(intake_db):
    factory, workspace, client = intake_db
    await send(intake_db, "August 2026 account DEMO", ["FB"], thread="10")
    await send(intake_db, "August 2026 account DEMO", ["FL"], thread="20")
    await send(intake_db, "cancel", thread="10")
    await send(intake_db, files=["FL"], thread="10")
    async with factory() as session:
        rows = list(await session.scalars(select(SlackIntake).where(SlackIntake.workspace_id == workspace.id)))
        assert {r.status for r in rows} == {"CANCELLED","WAITING"}
        assert not await session.scalar(select(Job.id).where(Job.workspace_id == workspace.id))


@db_test
@pytest.mark.asyncio
async def test_same_message_files_and_file_shared_do_not_duplicate(intake_db):
    factory, workspace, client = intake_db
    await send(intake_db, "August 2026 account DEMO", ["FB","FL"])
    await send(intake_db, type="file_shared", file_id="FB", files=[])
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Job).where(Job.workspace_id == workspace.id)) == 1
        intake = await session.scalar(select(SlackIntake).where(SlackIntake.workspace_id == workspace.id))
        assert await session.scalar(select(func.count()).select_from(SlackIntakeFile).where(SlackIntakeFile.intake_id == intake.id)) == 2


@db_test
@pytest.mark.asyncio
async def test_invalid_source_recovered_without_partial_import(intake_db):
    factory, workspace, client = intake_db
    original = client.download
    client.download = lambda r: httpx.Response(200, content=b"not a csv") if r.url.path == "/FL" else original(r)
    await send(intake_db, "August 2026 account DEMO", ["FB","FL"])
    client.download = original
    client.files["FL2"] = client.files["FL"]
    await send(intake_db, files=["FL2"])
    async with factory() as session:
        job = await session.scalar(select(Job).where(Job.workspace_id == workspace.id))
        assert job
    await process_intake(job, sessionmaker=factory)
    async with factory() as session:
        intake = await session.scalar(select(SlackIntake).where(SlackIntake.workspace_id == workspace.id))
        assert intake.status == "PROCESSED"


@db_test
@pytest.mark.asyncio
async def test_retry_downloads_same_inaccessible_file_after_access_restored(intake_db):
    factory, workspace, client = intake_db
    original = client.download
    client.download = lambda r: httpx.Response(403) if r.url.path == "/FL" else original(r)
    await send(intake_db, "August 2026 account DEMO", ["FB","FL"])
    client.download = original
    await send(intake_db, "retry")
    async with factory() as session:
        intake = await session.scalar(select(SlackIntake).where(SlackIntake.workspace_id == workspace.id))
        assert intake.status == "PROCESSING"
        assert set(intake.selected_files) == {"bank","ledger"}
    assert client.reads.count("FL") == 2


@db_test
@pytest.mark.asyncio
async def test_valid_selected_source_requires_explicit_replacement(intake_db):
    factory, workspace, client = intake_db
    client.files["FL2"] = client.files["FL"]
    original = client.download
    # Toggle a UTF-8 BOM to preserve valid content with a different hash.
    def changed(request):
        if request.url.path == "/FL2":
            data = (FIXTURES/client.files["FL2"]).read_bytes()
            return httpx.Response(200, content=data[3:] if data.startswith(b"\xef\xbb\xbf") else b"\xef\xbb\xbf"+data)
        return original(request)
    client.download = changed
    await send(intake_db, files=["FL"])
    async with factory() as session:
        intake = await session.scalar(select(SlackIntake).where(SlackIntake.workspace_id == workspace.id))
        original_id = intake.selected_files["ledger"]
    await send(intake_db, files=["FL2"])
    async with factory() as session:
        intake = await session.get(SlackIntake,intake.id)
        assert intake.selected_files["ledger"] == original_id
    await send(intake_db, "replace ledger", ["FL2"])
    async with factory() as session:
        intake = await session.get(SlackIntake,intake.id)
        assert intake.selected_files["ledger"] != original_id


@db_test
@pytest.mark.asyncio
async def test_expired_delivery_lease_recovers_with_stable_message_id(intake_db):
    factory, workspace, client = intake_db
    async with factory() as session, session.begin():
        row = await dispatcher.enqueue(session,workspace_id=workspace.id,channel_id="C_A",builder="test",message={"text":"test"})
        row.state, row.attempts = "LEASED", 1
        row.leased_until = utcnow() - timedelta(seconds=10)
    async with factory() as session:
        assert await dispatcher.dispatch_once(session,client)
        current = await session.get(SlackOutbox,row.id)
        assert current.state == "SENT" and current.attempts == 2
    assert client.posts[0]["client_msg_id"] == str(row.id)


@db_test
@pytest.mark.asyncio
async def test_wrong_period_rolls_back_and_context_correction_retries(intake_db):
    factory, workspace, _ = intake_db
    await send(intake_db, "August 2025 account DEMO", ["FB","FL"])
    async with factory() as session:
        job = await session.scalar(select(Job).where(Job.workspace_id == workspace.id))
    await process_intake(job, sessionmaker=factory)
    async with factory() as session:
        assert not await session.scalar(select(Reconciliation.id).where(Reconciliation.workspace_id == workspace.id))
    await send(intake_db, "August 2026")
    async with factory() as session:
        jobs = list(await session.scalars(select(Job).where(Job.workspace_id == workspace.id).order_by(Job.created_at)))
        assert len(jobs) == 2
    await process_intake(jobs[-1], sessionmaker=factory)


@db_test
@pytest.mark.asyncio
async def test_outbox_dedupe_permalink_failure_and_channel_pacing(intake_db):
    factory, workspace, client = intake_db
    async with factory() as session, session.begin():
        first = await dispatcher.enqueue(session, workspace_id=workspace.id, channel_id="C_A", builder="test", message={"text":"test"},idempotency_key=str(workspace.id))
        again = await dispatcher.enqueue(session, workspace_id=workspace.id, channel_id="C_A", builder="test", message={"text":"test"},idempotency_key=str(workspace.id))
        assert first.id == again.id
        await dispatcher.enqueue(session, workspace_id=workspace.id, channel_id="C_A", builder="test", message={"text":"second"})
        await dispatcher.enqueue(session, workspace_id=workspace.id, channel_id="C_B", builder="test", message={"text":"other channel"})
    async with factory() as session:
        assert await dispatcher.dispatch_once(session,client)
        assert await dispatcher.dispatch_once(session,client)
        assert not await dispatcher.dispatch_once(session,client)
        row = await session.get(SlackOutbox, first.id)
        assert row.state == "SENT" and row.attempts == 1
    assert [p["channel"] for p in client.posts] == ["C_A","C_B"]
    assert client.posts[0]["client_msg_id"] == str(first.id)


@db_test
@pytest.mark.asyncio
async def test_rate_limit_and_failure_cap(intake_db):
    factory, workspace, client = intake_db
    response = SlackResponse(client=None,http_verb="POST",api_url="https://slack.com/api/chat.postMessage",req_args={},data={"ok":False,"error":"ratelimited"},headers={"Retry-After":"30"},status_code=429)
    client.failure = SlackApiError("limited",response)
    async with factory() as session, session.begin():
        row = await dispatcher.enqueue(session,workspace_id=workspace.id,channel_id="C_A",builder="test",message={"text":"test"})
    async with factory() as session:
        await dispatcher.dispatch_once(session,client)
        await session.refresh(row := await session.get(SlackOutbox,row.id))
        assert row.state == "PENDING" and row.attempts == 1
        assert row.available_at > utcnow() + timedelta(seconds=20)
        assert not await dispatcher.dispatch_once(session,client)
    client.failure = RuntimeError("temporary failure")
    for attempt in range(2,6):
        async with factory() as session, session.begin():
            await session.execute(update(Workspace).where(Workspace.id == workspace.id).values(slack_retry_at=None))
            await session.execute(update(SlackOutbox).where(SlackOutbox.id == row.id).values(available_at=utcnow()-timedelta(seconds=1)))
        async with factory() as session:
            await dispatcher.dispatch_once(session,client)
            current = await session.get(SlackOutbox,row.id)
            assert current.attempts == attempt
            assert current.state == ("FAILED" if attempt == 5 else "PENDING")


@db_test
@pytest.mark.asyncio
async def test_signed_endpoint_routes_and_dedupes_without_slack_calls(intake_db):
    from app.main import app
    from app.core.db import get_session
    from app.core.config import get_settings
    factory, workspace, client = intake_db
    async def session_override():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_session] = session_override
    secret = get_settings().slack_signing_secret
    def headers(body):
        ts = str(int(time.time()))
        sig = hmac.new(secret.encode(),b"v0:"+ts.encode()+b":"+body,hashlib.sha256).hexdigest()
        return {"X-Slack-Request-Timestamp":ts,"X-Slack-Signature":"v0="+sig,"content-type":"application/json"}
    payload = {"type":"event_callback","team_id":workspace.slack_team_id,"event_id":str(uuid.uuid4()),"event":{"type":"app_mention","user":"U_OWNER","channel":"C_TEST","ts":"1.0","text":"reconcile August 2026 account DEMO"}}
    body = json.dumps(payload).encode()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as http:
            assert (await http.post("/slack/events", content=body,headers=headers(body))).status_code == 200
            assert (await http.post("/slack/events", content=body,headers=headers(body))).status_code == 200
            assert (await http.post("/slack/events", content=body,headers={})).status_code == 401
            malformed = b'{"event":[]}'
            assert (await http.post("/slack/events",content=malformed,headers=headers(malformed))).status_code == 400
        async with factory() as session:
            jobs = list(await session.scalars(select(Job).where(Job.workspace_id == workspace.id)))
            assert len(jobs) == 1 and jobs[0].kind == "slack_intake"
        assert not client.reads and not client.posts
    finally:
        app.dependency_overrides.pop(get_session,None)
