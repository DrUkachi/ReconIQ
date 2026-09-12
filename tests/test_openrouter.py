from copy import deepcopy
import json

import httpx
import pytest
from sqlalchemy import select, func

from app.core.config import get_settings
from app.core.logging import redact
from app.models.infra import SlackOutbox
from app.models.slack_chat import SlackChatTurn
from app.models.slack_intake import SlackIntake
from app.services.llm.client import LLMClient
from app.services.llm.openrouter import OpenRouterClient, OpenRouterUnavailable
from app.services.slack.chat import handle_chat
from app.services.slack.events import classify_event
from app.services.slack.intake_rules import is_intake_update
from tests.test_slack_intake import intake_db, db_test, event, send


@pytest.fixture(autouse=True)
def configure(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_model", "openai/gpt-5.6-luna")
    monkeypatch.setattr(settings, "openrouter_api_url", "https://openrouter.ai/api/v1/chat/completions")
    monkeypatch.setattr(settings, "openrouter_reasoning_enabled", True)


def api_message(content="Hello", **extra):
    return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content, **extra}}]}


def test_auth_model_reasoning_and_opaque_history_on_every_call():
    requests = []
    reasoning = [{"type":"reasoning.encrypted", "data":"opaque-payload", "id":"r1", "format":"openai-responses-v1", "index":0}]
    def api(request):
        requests.append(request)
        return httpx.Response(200,json=api_message("Three",reasoning_details=reasoning))
    client = OpenRouterClient(api_key="test-secret",transport=httpx.MockTransport(api))
    messages = [{"role":"user","content":"How many r letters are in strawberry?"}]
    first = client.complete(messages)
    messages.extend([first,{"role":"user","content":"Are you sure?"}])
    original = deepcopy(messages)
    client.complete(messages)
    assert messages == original
    for request in requests:
        body = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer test-secret"
        assert body["model"] == "openai/gpt-5.6-luna"
        assert body["reasoning"] == {"enabled":True}
        assert "tools" not in body
    assert json.loads(requests[1].content)["messages"][1]["reasoning_details"] == reasoning


@pytest.mark.parametrize("status", [301,401,402,429,500])
def test_http_failures_do_not_expose_response_body_or_key(status):
    client = OpenRouterClient(api_key="never-log-me",transport=httpx.MockTransport(
        lambda r:httpx.Response(status,json={"error":{"message":"never-log-me"}})))
    with pytest.raises(OpenRouterUnavailable) as exc:
        client.complete([{"role":"user","content":"hello"}])
    assert str(exc.value) == f"openrouter_http_{status}"


@pytest.mark.parametrize("payload", [[], {}, {"error":{"message":"secret"}}, {"choices":[]}, {"choices":[{"message":None}]}, api_message(None), api_message("", reasoning_details=[{"text":"private reasoning"}]), api_message("hello",tool_calls=[{"name":"approve"}])])
def test_invalid_responses_fail_safely(payload):
    client = OpenRouterClient(api_key="test",transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload)))
    with pytest.raises(OpenRouterUnavailable):
        client.complete([])


def test_no_key_and_untrusted_destination_fail_before_network(monkeypatch):
    with pytest.raises(OpenRouterUnavailable,match="key_missing"):
        OpenRouterClient(api_key="").complete([])
    monkeypatch.setattr(get_settings(),"openrouter_api_url","https://example.com/api/v1/chat/completions")
    with pytest.raises(OpenRouterUnavailable,match="url_invalid"):
        OpenRouterClient(api_key="secret").complete([])


def test_openrouter_structured_response_is_schema_validated():
    calls = []
    def api(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json=api_message(json.dumps({"counterparty":42})))
    client = OpenRouterClient(api_key="test",transport=httpx.MockTransport(api))
    llm = LLMClient(api_key="test",client=client,provider="openrouter")
    assert llm.extract_counterparty("TRF FROM SOMEONE") is None
    assert len(calls) == 2
    assert calls[0]["response_format"]["json_schema"]["strict"] is True
    assert llm.budget.total == 2


def test_openrouter_key_redaction():
    assert "sk-or-v1-abcd1234secret" not in redact("Bearer sk-or-v1-abcd1234secret")


@pytest.mark.parametrize("text,kind", [("<@U_BOT> hello", "agent_turn"), ("<@U_BOT> What is reconciliation?", "agent_turn"), ("<@U_BOT> reconcile August 2026 account DEMO", "slack_intake")])
def test_mentions_route_chat_or_intake(text,kind):
    for event_type in ["app_mention","message"]:
        route = classify_event({"type":"event_callback","event":{"type":event_type,"user":"U_HUMAN","text":text}},bot_user_id="U_BOT")
        assert route.job_kind == kind


@pytest.mark.parametrize("message,expected", [("How is August 2026 doing?",False), ("Explain account 1234",False), ("August 2026 account 1234",True), ("retry",True), ("What should I upload?",False)])
def test_questions_cannot_edit_intake_context(message,expected):
    assert is_intake_update({"text":message}) == expected


class FakeAI:
    def __init__(self,fail=False):
        self.calls = []
        self.fail = fail

    def complete(self,messages):
        self.calls.append(deepcopy(messages))
        if self.fail:
            raise OpenRouterUnavailable("openrouter_http_503")
        return {"role":"assistant","content":"Visible answer", "reasoning_details":[{"type":"reasoning.encrypted","data":"never-post-this"}]}


@db_test
@pytest.mark.asyncio
async def test_chat_replays_history_isolation_and_reasoning_not_posted(intake_db):
    factory, workspace, _ = intake_db
    ai = FakeAI()
    first = event(workspace,"Hello",ts="10.1",thread="10.1")
    await handle_chat(first,sessionmaker=factory,client=ai)
    await handle_chat(first,sessionmaker=factory,client=ai)
    await handle_chat(event(workspace,"Are you sure?",ts="10.2",thread="10.1"),sessionmaker=factory,client=ai)
    await handle_chat(event(workspace,"New conversation",ts="20.1",thread="20.1"),sessionmaker=factory,client=ai)
    assert len(ai.calls) == 3
    assert ai.calls[1][-2]["reasoning_details"] == [{"type":"reasoning.encrypted","data":"never-post-this"}]
    assert len(ai.calls[2]) == 2
    async with factory() as session:
        turns = list(await session.scalars(select(SlackChatTurn).where(SlackChatTurn.workspace_id == workspace.id)))
        posts = list(await session.scalars(select(SlackOutbox).where(SlackOutbox.workspace_id == workspace.id)))
        assert len(turns) == len(posts) == 3
        assert all(post.fallback_text == "Visible answer" for post in posts)
        assert not await session.scalar(select(SlackIntake.id).where(SlackIntake.workspace_id == workspace.id))


@db_test
@pytest.mark.asyncio
async def test_chat_rejects_bots_cross_channel_and_wrong_team(intake_db):
    factory,workspace,_=intake_db
    ai=FakeAI()
    for overrides in [{"user":"U_BOT"},{"channel":"C_OTHER"},{"bot_id":"B_OTHER"}]:
        await handle_chat(event(workspace,"hello",**overrides),sessionmaker=factory,client=ai)
    wrong=event(workspace,"hello")
    wrong.payload["team_id"]="T_OTHER"
    await handle_chat(wrong,sessionmaker=factory,client=ai)
    assert not ai.calls


@db_test
@pytest.mark.asyncio
async def test_chat_failure_posts_safe_fallback_once(intake_db):
    factory,workspace,_=intake_db
    ai=FakeAI(fail=True)
    job=event(workspace,"hello")
    await handle_chat(job,sessionmaker=factory,client=ai)
    await handle_chat(job,sessionmaker=factory,client=ai)
    async with factory() as session:
        turn=await session.scalar(select(SlackChatTurn).where(SlackChatTurn.workspace_id == workspace.id))
        assert turn.error_code == "openrouter_http_503"
        post=await session.scalar(select(SlackOutbox).where(SlackOutbox.workspace_id == workspace.id))
        assert "try your question again" in post.fallback_text
    assert len(ai.calls) == 1


@db_test
@pytest.mark.asyncio
async def test_chat_uses_only_current_intake_snapshot(intake_db):
    factory,workspace,_=intake_db
    await send(intake_db,"August 2026 account DEMO",thread="1.0")
    ai=FakeAI()
    await handle_chat(event(workspace,"What is missing?",ts="3.0"),sessionmaker=factory,client=ai)
    snapshot=next(m["content"] for m in ai.calls[0] if m["content"].startswith("Current thread snapshot"))
    assert '"status": "WAITING"' in snapshot
    assert '"account_last4": "DEMO"' in snapshot
    async with factory() as session:
        intake=await session.scalar(select(SlackIntake).where(SlackIntake.workspace_id == workspace.id))
        assert intake.status == "WAITING" and not intake.selected_files


@db_test
@pytest.mark.asyncio
async def test_signed_followup_routes_to_chat_and_context_update_stays_intake(intake_db):
    import hashlib
    import hmac
    import time
    import uuid
    from app.main import app
    from app.core.db import get_session
    from app.models.infra import Job
    factory,workspace,_=intake_db
    await send(intake_db,"August 2026 account DEMO",thread="1.0")
    await handle_chat(event(workspace,"hello",thread="20.0",ts="20.0"),sessionmaker=factory,client=FakeAI())
    async def session_override():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_session]=session_override
    try:
        for thread,prompt,expected in [("1.0","What is missing?","agent_turn"),("1.0","September 2026","slack_intake"),("20.0","And how does that work?","agent_turn")]:
            eid=str(uuid.uuid4())
            body=json.dumps({"type":"event_callback","event_id":eid,"team_id":workspace.slack_team_id,
                "event":{"type":"message","channel":"C_TEST","user":"U_OWNER","ts":"99.0","thread_ts":thread,"text":prompt}}).encode()
            stamp=str(int(time.time()))
            signature=hmac.new(get_settings().slack_signing_secret.encode(),b"v0:"+stamp.encode()+b":"+body,hashlib.sha256).hexdigest()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
                response=await client.post("/slack/events",content=body,headers={"X-Slack-Request-Timestamp":stamp,"X-Slack-Signature":"v0="+signature})
                assert response.status_code == 200
            async with factory() as session:
                job=await session.scalar(select(Job).where(Job.idempotency_key == f"event:{eid}"))
                assert job.kind == expected
    finally:
        app.dependency_overrides.pop(get_session,None)
