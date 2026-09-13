import hashlib
import logging
from typing import Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BankReconError, ErrorCode
from app.domain.enums import Role
from app.models.core import AppUser, Workspace

logger = logging.getLogger(__name__)

# (workspace, slack member id, display name) for the first installed Slack workspace
# whose verified member email matches, or None.
SlackLookup = Callable[[AsyncSession, str], Awaitable[tuple[Workspace, str, str] | None]]


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        raise BankReconError(
            ErrorCode.E_VALIDATION, detail="Supply a valid work email address."
        )
    return email


def mask_email(value: str) -> str:
    local, _, domain = normalize_email(value).partition("@")
    visible = local[:2] if len(local) > 1 else local[:1]
    hidden = "*" * max(1, len(local) - len(visible))
    return f"{visible}{hidden}@{domain}"


def web_workspace_key(email: str) -> str:
    # Keyed by the full address: a shared mail domain (gmail.com) must never share data.
    digest = hashlib.sha256(f"workspace:{normalize_email(email)}".encode("utf-8")).hexdigest()
    return "WEB_" + digest[:28]


def web_user_key(email: str) -> str:
    return "WEB_" + hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()[:28]


def display_name(name: str | None, email: str) -> str:
    candidate = (name or "").strip()
    if candidate:
        return candidate[:255]
    local = normalize_email(email).split("@", 1)[0]
    return local.replace(".", " ").replace("_", " ").title()[:255]


def workspace_name(name: str | None, email: str) -> str:
    candidate = (name or "").strip()
    if candidate:
        return candidate[:255]
    local = normalize_email(email).split("@", 1)[0]
    return f"{local.replace('.', ' ').replace('_', ' ').replace('-', ' ').title()} Workspace"[:255]


async def find_slack_membership(session: AsyncSession, email: str) -> tuple[Workspace, str, str] | None:
    """Look the signed-in email up in each installed Slack workspace (needs users:read.email)."""
    from app.services.slack.client import slack_client

    workspaces = (await session.execute(
        select(Workspace).where(
            Workspace.bot_token.is_not(None),
            Workspace.bot_token != "",
            Workspace.uninstalled_at.is_(None),
            ~Workspace.slack_team_id.startswith("WEB_"),
        ).order_by(Workspace.created_at)
    )).scalars().all()
    for workspace in workspaces:
        try:
            response = await slack_client(workspace.bot_token).users_lookupByEmail(email=email)
        except Exception as exc:  # users_not_found, missing_scope, network: fall through
            error = getattr(getattr(exc, "response", None), "get", lambda *_: None)("error")
            logger.info("slack_email_lookup_miss", extra={"component": "web_auth", "outcome": str(error or type(exc).__name__)})
            continue
        member = response.get("user") or {}
        if member.get("id") and not member.get("deleted") and not member.get("is_bot"):
            profile = member.get("profile") or {}
            name = profile.get("real_name") or member.get("real_name") or member.get("name") or ""
            return workspace, member["id"], name
    return None


async def ensure_web_identity(
    session: AsyncSession,
    *,
    email: str,
    name: str | None = None,
    workspace: str | None = None,
    slack_lookup: SlackLookup | None = find_slack_membership,
) -> tuple[Workspace, AppUser]:
    """Sign a verified web email in as its Slack member when the email belongs to an
    installed Slack workspace, so the dashboard shows the reconciliations run in Slack.
    Otherwise the email gets its own private workspace."""
    normalized_email = normalize_email(email)

    membership = await slack_lookup(session, normalized_email) if slack_lookup else None
    if membership is not None:
        slack_workspace, member_id, slack_name = membership
        user = (await session.execute(select(AppUser).where(
            AppUser.workspace_id == slack_workspace.id, AppUser.slack_user_id == member_id,
        ))).scalar_one_or_none()
        if user is None:
            user = AppUser(workspace_id=slack_workspace.id, slack_user_id=member_id, role=Role.MEMBER)
            session.add(user)
        user.display_name = display_name(slack_name or name, normalized_email)
        user.email_masked = mask_email(normalized_email)
        await session.flush()
        return slack_workspace, user

    workspace_key = web_workspace_key(normalized_email)
    user_key = web_user_key(normalized_email)

    row = (
        await session.execute(
            select(Workspace).where(Workspace.slack_team_id == workspace_key)
        )
    ).scalar_one_or_none()
    if row is None:
        row = Workspace(slack_team_id=workspace_key, name=workspace_name(workspace, normalized_email))
        session.add(row)
        await session.flush()

    user = (
        await session.execute(
            select(AppUser).where(
                AppUser.workspace_id == row.id,
                AppUser.slack_user_id == user_key,
            )
        )
    ).scalar_one_or_none()
    if user is None:
        count = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(AppUser)
                    .where(AppUser.workspace_id == row.id)
                )
            ).scalar_one()
        )
        user = AppUser(
            workspace_id=row.id,
            slack_user_id=user_key,
            display_name=display_name(name, normalized_email),
            email_masked=mask_email(normalized_email),
            role=Role.OWNER if count == 0 else Role.APPROVER,
        )
        session.add(user)
        await session.flush()
    else:
        user.display_name = display_name(name, normalized_email)
        user.email_masked = mask_email(normalized_email)
        if workspace and workspace.strip():
            row.name = workspace_name(workspace, normalized_email)
        await session.flush()

    return row, user


def session_payload(workspace: Workspace, user: AppUser) -> dict:
    return {
        "user": {
            "id": user.id,
            "display_name": user.display_name,
            "email_masked": user.email_masked,
            "role": user.role,
            "slack_user_id": user.slack_user_id,
        },
        "workspace": {"id": workspace.id, "name": workspace.name},
    }
