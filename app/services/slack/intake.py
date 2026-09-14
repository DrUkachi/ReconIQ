"""Durable thread intake. Only signed Slack messages supply commands/context."""
import asyncio
import hashlib
import re
import uuid
import httpx

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.errors import BankReconError, ErrorCode
from app.core.rbac import Action, AuthzContext, require
from app.domain.enums import Role
from app.models.core import AppUser, Workspace
from app.models.slack_intake import SlackIntake, SlackIntakeFile
from app.services import audit
from app.services.ingestion.files import parse_ledger_csv, parse_signed_pdf
from app.services.cases.team_routing import enqueue_routing
from app.services.ingestion.persistence import import_signed_sources
from app.services.jobs import queue
from app.services.matching.persistence import match_reconciliation
from app.services.outbox import dispatcher
from app.services.slack.client import download_file, file_info, slack_client
from app.services.slack.intake_rules import file_role, parse_context


async def say(session, intake, text, key):
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    await dispatcher.enqueue(session, workspace_id=intake.workspace_id,
        channel_id=intake.channel_id, thread_ts=intake.thread_ts, builder="intake",
        message={"text": text}, idempotency_key=f"intake:{intake.id}:{key}")


async def locked(session, workspace_id, intake_id=None):
    workspace = await session.scalar(select(Workspace).where(
        Workspace.id == workspace_id).with_for_update())
    intake = None
    if intake_id:
        intake = await session.scalar(select(SlackIntake).where(
            SlackIntake.id == intake_id, SlackIntake.workspace_id == workspace_id).with_for_update())
    return workspace, intake


def parse_file(content, filename, role):
    return parse_ledger_csv(content, filename) if role == "ledger" or filename.lower().endswith(".csv") else parse_signed_pdf(content, filename)


async def handle_intake_event(job, *, sessionmaker=None, client=None, transport=None):
    factory = sessionmaker or get_sessionmaker()
    event = job.payload.get("event") or {}
    if event.get("bot_id") or event.get("subtype") in {"bot_message", "message_changed", "message_deleted"}:
        return
    user_id = event.get("user") or event.get("user_id")
    channel = event.get("channel") or event.get("channel_id")
    if not user_id or not channel:
        return
    # file_shared carries no reliable thread text. The canonical message event
    # supplies context; accept a share only when its exact channel has one origin.
    async with factory() as session:
        workspace = await session.get(Workspace, job.workspace_id)
        if not workspace or workspace.uninstalled_at or job.payload.get("team_id") != workspace.slack_team_id:
            return
        if workspace.recon_channel_id != channel or user_id == workspace.bot_user_id:
            return
        token = workspace.bot_token or ""
        actor = await session.scalar(select(AppUser).where(AppUser.workspace_id == workspace.id, AppUser.slack_user_id == user_id))
        authorized = actor and Role(actor.role) in {Role.OWNER, Role.APPROVER}
    if event.get("type") == "file_shared":
        if not authorized:
            return
        info = await file_info(client or slack_client(token), event.get("file_id") or (event.get("file") or {}).get("id"))
        shares = [s for scope in (info.get("shares") or {}).values() for s in scope.get(channel, [])]
        roots = {s.get("thread_ts") or s.get("ts") for s in shares}
        if len(roots) != 1 or None in roots:
            return
        event = {**event, "thread_ts": roots.pop(), "files": [info]}
    thread = event.get("thread_ts") or event.get("ts")
    if not thread:
        return
    message = event.get("text") or ""
    event_key = job.payload.get("event_id") or str(job.id)
    pending = []
    async with factory() as session, session.begin():
        workspace, _ = await locked(session, job.workspace_id)
        actor = await session.scalar(select(AppUser).where(AppUser.workspace_id == workspace.id, AppUser.slack_user_id == user_id))
        if not actor:
            actor = AppUser(workspace_id=workspace.id, slack_user_id=user_id, role=Role.MEMBER)
            session.add(actor)
            await session.flush()
        try:
            auth = AuthzContext(role=Role(actor.role), actor_user_id=str(actor.id))
            require(Action.UPLOAD_STATEMENT, auth)
            require(Action.LOAD_LEDGER, auth)
        except BankReconError:
            await audit.record(session, workspace_id=workspace.id, actor_user_id=actor.id,
                action="AUTHZ_DENIED", detail={"action": "slack_intake"})
            await dispatcher.enqueue(session, workspace_id=workspace.id, channel_id=channel, thread_ts=thread,
                builder="intake", message={"text": "An Owner or Approver must start or change reconciliation intake."},
                idempotency_key=f"intake-denied:{workspace.id}:{event_key}")
            return
        intake = await session.scalar(select(SlackIntake).where(SlackIntake.workspace_id == workspace.id,
            SlackIntake.channel_id == channel, SlackIntake.thread_ts == thread).with_for_update())
        if not intake:
            intake = SlackIntake(workspace_id=workspace.id, actor_user_id=actor.id, channel_id=channel, thread_ts=thread)
            session.add(intake)
            await session.flush()
        if intake.status != "WAITING":
            attached = [f.get("id") for f in event.get("files") or []]
            known = set(await session.scalars(select(SlackIntakeFile.slack_file_id).where(
                SlackIntakeFile.intake_id == intake.id, SlackIntakeFile.slack_file_id.in_(attached)))) if attached else set()
            if attached and set(attached) <= known:
                return
            if message.strip().lower() in {"status", "retry", "cancel"}:
                await say(session, intake, f"Intake status: {intake.status}. Existing runs remain available; start a new thread for another intake.", event_key)
            elif event.get("files") or parse_context(message).account or parse_context(message).start:
                await say(session, intake, f"This intake is {intake.status}; its selected sources cannot be changed. Use a new thread for another intake.", event_key)
            return
        if re.fullmatch(r"\s*cancel\s*", message, re.I):
            intake.status = "CANCELLED"
            await say(session, intake, "Intake cancelled. No reconciliation was created from this intake.", event_key)
            return
        context = parse_context(message)
        if context.error:
            await say(session, intake, context.error, event_key)
            return
        changed = False
        for name, value in (("account_last4", context.account), ("period_start", context.start), ("period_end", context.end)):
            if value is not None and getattr(intake, name) != value:
                setattr(intake, name, value)
                changed = True
        if changed or message.strip().lower() == "retry":
            intake.revision += 1
        intake.actor_user_id = actor.id
        if message.strip().lower() == "retry":
            retry_files = list(await session.scalars(select(SlackIntakeFile).where(
                SlackIntakeFile.intake_id == intake.id, SlackIntakeFile.state.in_(["INVALID", "PENDING"]))))
            for row in retry_files:
                row.state = "PENDING"
                pending.append(row.id)
        for attachment in event.get("files") or []:
            fid = attachment.get("id")
            if not fid:
                continue
            row = await session.scalar(select(SlackIntakeFile).where(SlackIntakeFile.intake_id == intake.id, SlackIntakeFile.slack_file_id == fid))
            if row and row.state != "PENDING":
                replacement = re.search(r"\breplace\s+(bank|statement|ledger)\b", message, re.I)
                replacement_role = "bank" if replacement and replacement[1].lower() in {"bank", "statement"} else "ledger"
                if replacement and row.role == replacement_role and row.state == "VALID":
                    row.state = "PENDING"
                else:
                    continue
            if not row:
                row = SlackIntakeFile(intake_id=intake.id, slack_file_id=fid, filename=attachment.get("name", ""),
                    role=file_role(attachment.get("name", ""), message))
                session.add(row)
                await session.flush()
            pending.append(row.id)
        intake_id = intake.id
        if pending:
            await say(session, intake, "Attachments received. I’m checking the files for this thread.", f"received:{event_key}")
    for file_id in pending:
        await receive_file(factory, job.workspace_id, intake_id, file_id, message,
            client or slack_client(token), token, transport)
    async with factory() as session, session.begin():
        _, intake = await locked(session, job.workspace_id, intake_id)
        await advance(session, intake)


async def receive_file(factory, workspace_id, intake_id, file_id, message, client, token, transport):
    async with factory() as session:
        row = await session.get(SlackIntakeFile, file_id)
        if row.state != "PENDING":
            return
        fid = row.slack_file_id
    content = None
    report = {}
    role = "unsupported"
    filename = "attachment"
    try:
        info = await file_info(client, fid)
        filename = info.get("name") or "attachment"
        role = file_role(filename, message)
        if role in {"context", "unsupported"}:
            state = "IGNORED"
            report = {"message": "Supporting context received; it will not be imported." if role == "context" else "Unsupported attachment. Upload a bank PDF and ledger CSV."}
        else:
            settings = get_settings()
            content = await download_file(info, token, settings.max_csv_bytes if filename.lower().endswith(".csv") else settings.max_pdf_bytes, transport=transport)
            parsed = await asyncio.to_thread(parse_file, content, filename, role)
            report = {"accepted": len(parsed.accepted), "rejected": len(parsed.rejected),
                "errors": [f"Row {r.source.index}: {', '.join(r.reasons)}" for r in parsed.rejected[:5]]}
            state = "VALID" if parsed.accepted and not parsed.rejected else "INVALID"
            report["message"] = f"{role.title()}: {report['accepted']} accepted rows, {report['rejected']} rejected rows."
            if role == "validation":
                report["message"] += " Validation only; these rows are excluded from reconciliation."
    except httpx.HTTPError as exc:
        state, report = "INVALID", {"message": "Slack file download failed. Reply retry to try again.", "code": type(exc).__name__}
    except BankReconError as exc:
        state, report = "INVALID", {"message": exc.message, "code": str(exc.code)}
    async with factory() as session, session.begin():
        _, intake = await locked(session, workspace_id, intake_id)
        row = await session.get(SlackIntakeFile, file_id)
        if row.state != "PENDING":
            return
        row.filename, row.role, row.content, row.state, row.report = filename, role, content, state, report
        row.sha256 = hashlib.sha256(content).hexdigest() if content is not None else None
        if state == "VALID" and role in {"bank", "ledger"} and intake.status == "WAITING":
            selected = dict(intake.selected_files)
            existing = await session.get(SlackIntakeFile, uuid.UUID(selected[role])) if role in selected else None
            replacement = bool(re.search(r"\breplace\s+" + (r"(?:bank|statement)" if role == "bank" else "ledger") + r"\b", message, re.I))
            if existing and existing.sha256 == row.sha256:
                report["message"] += " Identical source already selected; no duplicate import."
            elif existing and not replacement:
                report["message"] += f" A {role} is already selected. To replace it before processing, upload again with ‘replace {role}’."
            else:
                selected[role] = str(row.id)
                intake.selected_files = selected
                intake.revision += 1
        row.report = dict(report)
        report_key = hashlib.sha256(str(report).encode()).hexdigest()
        await say(session, intake, report["message"] + ("\n" + "\n".join(report["errors"]) if report.get("errors") else ""), f"file:{row.id}:{report_key}")


async def advance(session, intake):
    if intake.status != "WAITING":
        return
    pending = await session.scalar(select(SlackIntakeFile.id).where(SlackIntakeFile.intake_id == intake.id, SlackIntakeFile.state == "PENDING").limit(1))
    if pending:
        return
    missing = [name for name in ("bank", "ledger") if name not in intake.selected_files]
    if not intake.account_last4:
        missing.append("account last four (e.g. account 1234)")
    if not intake.period_start:
        missing.append("period (e.g. August 2026)")
    if missing:
        prompt = "Reply in this thread with: " + ", ".join(missing) + ". Files can arrive in either order."
        digest = hashlib.sha256(prompt.encode()).hexdigest()
        if digest != intake.last_prompt:
            await say(session, intake, prompt, f"prompt:{intake.revision}:{digest}")
            intake.last_prompt = digest
        return
    queued = await queue.enqueue(session, kind="process_intake", workspace_id=intake.workspace_id,
        idempotency_key=f"intake:{intake.id}:process:{intake.revision}",
        payload={"intake_id": str(intake.id), "revision": intake.revision})
    if queued is None:
        return
    intake.status = "PROCESSING"
    await say(session, intake, f"Processing account ending {intake.account_last4}, {intake.period_start} to {intake.period_end}. Currencies will be reconciled separately.", f"processing:{intake.revision}")


async def process_intake(job, *, sessionmaker=None):
    factory = sessionmaker or get_sessionmaker()
    async with factory() as session, session.begin():
        workspace, intake = await locked(session, job.workspace_id, uuid.UUID(job.payload["intake_id"]))
        if not workspace or workspace.uninstalled_at or not intake or intake.status != "PROCESSING" or intake.revision != job.payload["revision"]:
            return
        try:
            async with session.begin_nested():
                sources = {}
                for role in ("bank", "ledger"):
                    row = await session.get(SlackIntakeFile, uuid.UUID(intake.selected_files[role]))
                    if row.intake_id != intake.id or row.state != "VALID":
                        raise BankReconError(ErrorCode.E_VALIDATION, detail="The selected source is unavailable.")
                    sources[role] = await asyncio.to_thread(parse_file, row.content, row.filename, role)
                ids = await import_signed_sources(session, workspace_id=workspace.id, actor_user_id=intake.actor_user_id,
                    account_last4=intake.account_last4, start=intake.period_start, end=intake.period_end,
                    bank=sources["bank"], ledger=sources["ledger"], channel_id=intake.channel_id)
                summaries = [await match_reconciliation(session, workspace_id=workspace.id, reconciliation_id=rid) for rid in ids]
        except BankReconError as exc:
            intake.status = "WAITING"
            intake.last_prompt = ""
            await say(session, intake, exc.message + " Correct the context or replace the source in this thread, then reply ‘retry’.", f"error:{intake.revision}")
            return
        intake.status = "PROCESSED"
        intake.reconciliation_ids = [str(rid) for rid in ids]
        for summary in summaries:
            counts = ", ".join(f"{key}: {value}" for key, value in summary["bank_status_counts"].items())
            routing = (f" ReconIQ is routing {summary['cases']} exception(s) to the teams that own them." if summary["cases"]
                       else " No exceptions, so no team was notified.")
            await say(session, intake, f"{summary['currency']} processing finished. {counts}. Cases: {summary['cases']}.{routing}\nRun: {summary['id']}. Review outstanding items before closing the reconciliation.", f"summary:{intake.revision}:{summary['currency']}")
        # The agent picks each exception's team in a worker job, after the summaries are queued.
        for rid in ids:
            await enqueue_routing(session, workspace_id=workspace.id, reconciliation_id=rid,
                                  notify_channel_id=intake.channel_id, notify_thread_ts=intake.thread_ts)
