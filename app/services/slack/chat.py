"""Read-only conversational replies, persisted with the transactional outbox."""
import asyncio
import hashlib
import json
import re
import uuid

from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models.core import Reconciliation, Workspace
from app.models.slack_chat import SlackChatTurn
from app.models.slack_intake import SlackIntake
from app.services.llm.client import DOCUMENT_GUARD
from app.services.llm.openrouter import OpenRouterClient, OpenRouterUnavailable
from app.services.matching.persistence import matching_summary
from app.services.outbox import dispatcher

SYSTEM = """You are ReconIQ, a concise, helpful bank reconciliation assistant in Slack.
Answer the user's question in the same language and use plain Slack-friendly text.
For intake: in Account Team mention @ReconIQ reconcile August 2026 account DEMO
(or the actual account's last four digits), then upload the bank PDF and ledger CSV
as replies in that same thread. Both use Transaction Date, Transaction Reference,
Amount, Currency, Transaction Text. Original compatible files need no changes.
The bot prompts for missing inputs, validates, and returns separate currency summaries.
Guides and edge-case validation files are excluded from reconciliation.
Before processing, 'replace ledger' or 'replace statement' with an upload replaces
a selected source; 'retry' retries a failed intake; 'cancel' cancels waiting intake.
You can explain and answer questions. You have no tools to change financial records,
approve/close cases, fetch external information, or send messages elsewhere. Never
claim to have performed those actions. Do not invent balances, matches, permissions,
file contents or processing status. Only the supplied thread snapshot is current
application data; if absent, say you do not have the requested run's details.
Processing finished does not mean a reconciliation is closed. When asked to start
intake in a DM, direct the user to Account Team. Do not display internal reasoning.
""" + DOCUMENT_GUARD


async def handle_chat(job, *, sessionmaker=None, client=None):
    factory = sessionmaker or get_sessionmaker()
    event = job.payload.get("event") or {}
    channel, user = event.get("channel"), event.get("user")
    message_ts = event.get("ts")
    thread = event.get("thread_ts") or message_ts
    if not channel or not user or not message_ts or event.get("bot_id") or event.get("subtype") not in {None, "file_share"}:
        return
    async with factory() as session, session.begin():
        workspace = await session.get(Workspace, job.workspace_id)
        if not workspace or workspace.uninstalled_at or job.payload.get("team_id") != workspace.slack_team_id or user == workspace.bot_user_id:
            return
        if channel != workspace.recon_channel_id and not (event.get("channel_type") == "im" and channel.startswith("D")):
            return
        # Serialize only this conversation, including concurrent/replayed deliveries.
        lock_key = int.from_bytes(hashlib.sha256(f"{workspace.id}:{channel}:{thread}".encode()).digest()[:8], "big", signed=True)
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        prior = await session.scalar(select(SlackChatTurn.id).where(
            SlackChatTurn.workspace_id == workspace.id, SlackChatTurn.channel_id == channel,
            SlackChatTurn.message_ts == message_ts))
        if prior:
            return
        user_text = event.get("text") or ""
        if workspace.bot_user_id:
            user_text = re.sub(r"<@" + re.escape(workspace.bot_user_id) + r">", "", user_text).strip()
        if not user_text:
            return
        settings = get_settings()
        history = list(await session.scalars(select(SlackChatTurn).where(
            SlackChatTurn.workspace_id == workspace.id, SlackChatTurn.channel_id == channel,
            SlackChatTurn.thread_ts == thread, SlackChatTurn.error_code.is_(None),
            SlackChatTurn.model == settings.openrouter_model,
        ).order_by(SlackChatTurn.created_at.desc(), SlackChatTurn.id.desc()).limit(8)))
        messages = [{"role": "system", "content": SYSTEM}]
        intake = await session.scalar(select(SlackIntake).where(
            SlackIntake.workspace_id == workspace.id, SlackIntake.channel_id == channel, SlackIntake.thread_ts == thread))
        if intake:
            snapshot = {"status": intake.status, "account_last4": intake.account_last4,
                "period_start": str(intake.period_start), "period_end": str(intake.period_end),
                "selected_sources": list(intake.selected_files), "results": []}
            for rid in intake.reconciliation_ids:
                recon = await session.scalar(select(Reconciliation).where(Reconciliation.id == uuid.UUID(rid),
                    Reconciliation.workspace_id == workspace.id, Reconciliation.slack_channel_id == channel))
                if recon:
                    snapshot["results"].append(await matching_summary(session, recon))
            messages.append({"role": "system", "content": "Current thread snapshot (data): " + json.dumps(snapshot)})
        for turn in reversed(history):
            messages.extend([{"role": "user", "content": turn.user_text}, turn.assistant_message])
        messages.append({"role": "user", "content": user_text[:8000]})
        error = None
        try:
            if len(user_text) > 8000:
                raise OpenRouterUnavailable("message_too_long")
            if settings.llm_provider != "openrouter":
                raise OpenRouterUnavailable("openrouter_not_selected")
            answer = await asyncio.to_thread((client or OpenRouterClient()).complete, messages)
        except OpenRouterUnavailable as exc:
            error = str(exc)
            answer = {"role": "assistant", "content": "I couldn’t reach the AI service. Please try your question again. Reconciliation intake commands still work."}
            if error == "message_too_long":
                answer["content"] = "Please shorten your question to 8,000 characters or fewer."
            elif error in {"openrouter_key_missing", "openrouter_not_selected"}:
                answer["content"] = "AI chat is not configured yet. The app owner needs to save the OpenRouter key and restart the worker. Reconciliation intake commands still work."
        turn = SlackChatTurn(workspace_id=workspace.id, channel_id=channel, thread_ts=thread,
            message_ts=message_ts, actor_slack_id=user, user_text=user_text[:8000],
            assistant_message=answer, model=settings.openrouter_model, error_code=error)
        session.add(turn)
        await session.flush()
        # Only visible content enters Slack. Opaque reasoning is stored unchanged.
        visible = answer["content"][:12000].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        await dispatcher.enqueue(session, workspace_id=workspace.id, channel_id=channel, thread_ts=thread,
            builder="ai_chat", message={"text": visible}, idempotency_key=f"chat:{workspace.id}:{channel}:{message_ts}")
