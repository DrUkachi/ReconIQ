import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.errors import BankReconError, ErrorCode
from app.core.rbac import Action, AuthzContext, require
from app.domain.enums import Role
from app.models.core import AppUser

# PRD section 12: workspace_id is derived from the session, never from the request
# body. A caller cannot address another workspace by changing a payload field.


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    slack_user_id: str
    role: Role

    def context(self, **overrides) -> AuthzContext:
        base = {
            "role": self.role,
            "actor_user_id": str(self.user_id),
        }
        base.update(overrides)
        return AuthzContext(**base)


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def current_principal(request: Request, session: SessionDep) -> Principal:
    """Resolve the signed-in user from the session cookie.

    The Slack OIDC exchange populates `request.session["user_id"]`; this dependency
    is the only place the rest of the API learns who is calling.
    """
    try:
        user_id = (request.session or {}).get("user_id")
    except (AssertionError, AttributeError):
        # Session middleware absent: treat as unauthenticated rather than a 500.
        user_id = None
    if not user_id:
        raise BankReconError(ErrorCode.E_AUTHZ, names="signed-in users")

    user = (
        await session.execute(select(AppUser).where(AppUser.id == uuid.UUID(str(user_id))))
    ).scalar_one_or_none()
    if user is None:
        raise BankReconError(ErrorCode.E_AUTHZ, names="signed-in users")

    return Principal(
        user_id=user.id,
        workspace_id=user.workspace_id,
        slack_user_id=user.slack_user_id,
        role=Role(user.role),
    )


PrincipalDep = Annotated[Principal, Depends(current_principal)]


def requires(action: Action):
    """Route-level role gate for actions whose check needs no per-row context."""

    async def dependency(principal: PrincipalDep) -> Principal:
        require(action, principal.context())
        return principal

    return Depends(dependency)


async def idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    """PRD section 12: every mutating endpoint requires an Idempotency-Key."""
    if not idempotency_key:
        raise BankReconError(
            ErrorCode.E_VALIDATION, detail="An Idempotency-Key header is required."
        )
    return idempotency_key


IdempotencyDep = Annotated[str, Depends(idempotency_key)]


@dataclass(frozen=True)
class Page:
    cursor: str | None = None
    limit: int = 50


async def pagination(cursor: str | None = None, limit: int = 50) -> Page:
    return Page(cursor=cursor, limit=max(1, min(limit, 50)))


PageDep = Annotated[Page, Depends(pagination)]
