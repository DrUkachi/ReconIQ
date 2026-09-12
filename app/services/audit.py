import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.models.base import utcnow
from app.models.infra import AuditEvent

# PRD section 07 rule 3: every mutating tool writes an audit_event inside the same
# transaction. This helper never commits; the caller owns the transaction boundary
# so that the audit row cannot survive a rolled-back mutation, or vice versa.


async def record(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    action: str,
    actor_user_id: uuid.UUID | None = None,
    actor_slack_id: str | None = None,
    reconciliation_id: uuid.UUID | None = None,
    case_id: uuid.UUID | None = None,
    from_state: str | None = None,
    to_state: str | None = None,
    reason: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        workspace_id=workspace_id,
        reconciliation_id=reconciliation_id,
        case_id=case_id,
        actor_user_id=actor_user_id,
        actor_slack_id=actor_slack_id,
        action=action,
        from_state=from_state,
        to_state=to_state,
        reason=reason,
        detail=detail or {},
        correlation_id=get_correlation_id(),
        created_at=utcnow(),
    )
    session.add(event)
    await session.flush()
    return event


async def record_authz_denied(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    action: str,
    actor_user_id: uuid.UUID | None = None,
    actor_slack_id: str | None = None,
    case_id: uuid.UUID | None = None,
) -> AuditEvent:
    """PRD rule A1: every authorisation failure writes an audit row and changes nothing."""
    return await record(
        session,
        workspace_id=workspace_id,
        action="AUTHZ_DENIED",
        actor_user_id=actor_user_id,
        actor_slack_id=actor_slack_id,
        case_id=case_id,
        detail={"attempted": action},
    )
