import json
import logging
from urllib.parse import parse_qs

from fastapi import APIRouter, Request, Response
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import SessionDep, SettingsDep
from app.core.correlation import get_correlation_id
from app.models.base import utcnow
from app.models.infra import ProcessedEvent, ProcessedInteraction
from app.services.jobs import queue
from app.services.slack.events import classify_event, classify_interaction, is_retry
from app.services.slack.verify import SignatureError, verify_signature

logger = logging.getLogger(__name__)

# PRD section 09. The 3 second ACK deadline governs this whole module: verify,
# dedupe, enqueue, return 200. No extraction, no matching, no model call, no
# Slack API call happens on this thread.

router = APIRouter(prefix="/slack", tags=["slack"])

OK = Response(status_code=200)


@router.post("/events")
async def events(request: Request, session: SessionDep, settings: SettingsDep) -> Response:
    body = await request.body()
    if not _verified(request, body, settings.slack_signing_secret):
        return Response(status_code=401)

    envelope = json.loads(body or b"{}")

    # Slack's one-time endpoint handshake.
    if envelope.get("type") == "url_verification":
        return Response(
            content=json.dumps({"challenge": envelope.get("challenge", "")}),
            media_type="application/json",
        )

    event_id = envelope.get("event_id")
    if not event_id:
        return OK

    # PRD section 14: dedupe on event_id. Zero rows affected means Slack is
    # retrying something already handled, so this returns 200 and does no work.
    inserted = await session.execute(
        insert(ProcessedEvent)
        .values(
            slack_event_id=event_id,
            event_type=(envelope.get("event") or {}).get("type", ""),
            received_at=utcnow(),
        )
        .on_conflict_do_nothing(index_elements=[ProcessedEvent.slack_event_id])
        .returning(ProcessedEvent.slack_event_id)
    )
    if inserted.scalar_one_or_none() is None:
        await session.commit()
        logger.info(
            "slack_event_duplicate",
            extra={
                "component": "slack",
                "action": "events",
                "outcome": "retry" if is_retry(dict(request.headers)) else "duplicate",
            },
        )
        return OK

    route = classify_event(envelope, bot_user_id=envelope.get("authed_user_id"))
    if route.ignored:
        await session.commit()
        logger.info(
            "slack_event_ignored",
            extra={"component": "slack", "action": "events", "outcome": route.reason},
        )
        return OK

    await queue.enqueue(
        session,
        kind=route.job_kind,
        idempotency_key=f"event:{event_id}",
        payload=route.payload,
    )
    await session.commit()
    logger.info(
        "slack_event_enqueued",
        extra={"component": "slack", "action": route.job_kind, "outcome": "queued"},
    )
    return OK


@router.post("/interactions")
async def interactions(
    request: Request, session: SessionDep, settings: SettingsDep
) -> Response:
    body = await request.body()
    if not _verified(request, body, settings.slack_signing_secret):
        return Response(status_code=401)

    parsed = parse_qs(body.decode())
    raw_payload = (parsed.get("payload") or ["{}"])[0]
    payload = json.loads(raw_payload)

    route = classify_interaction(payload)
    if route.ignored:
        logger.info(
            "slack_interaction_ignored",
            extra={"component": "slack", "action": route.action_id, "outcome": route.reason},
        )
        return OK

    # PRD section 14: interaction payload replay guard, deduped on trigger_id.
    if route.trigger_id:
        inserted = await session.execute(
            insert(ProcessedInteraction)
            .values(trigger_id=route.trigger_id, received_at=utcnow())
            .on_conflict_do_nothing(index_elements=[ProcessedInteraction.trigger_id])
            .returning(ProcessedInteraction.trigger_id)
        )
        if inserted.scalar_one_or_none() is None:
            await session.commit()
            return OK

    # The acting user is taken from the payload Slack signed. RBAC is applied in
    # the worker against this id, never against anything in the button value.
    await queue.enqueue(
        session,
        kind="interaction",
        idempotency_key=f"interaction:{route.trigger_id or route.message_ts}",
        payload={
            "handler": route.handler,
            "action_id": route.action_id,
            "value": route.value,
            "actor_slack_id": route.user_slack_id,
            "channel_id": route.channel_id,
            "message_ts": route.message_ts,
            "team_id": (payload.get("team") or {}).get("id"),
        },
    )
    await session.commit()
    logger.info(
        "slack_interaction_enqueued",
        extra={"component": "slack", "action": route.handler, "outcome": "queued"},
    )
    return OK


def _verified(request: Request, body: bytes, signing_secret: str) -> bool:
    """Signature failure is logged and refused; it never reaches the router."""
    try:
        verify_signature(
            signing_secret,
            request.headers.get("X-Slack-Request-Timestamp"),
            request.headers.get("X-Slack-Signature"),
            body,
        )
        return True
    except SignatureError as exc:
        logger.warning(
            "slack_signature_rejected",
            extra={"component": "slack", "action": "verify", "outcome": str(exc)},
        )
        return False
