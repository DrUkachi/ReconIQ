import hashlib

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BankReconError, ErrorCode
from app.domain.enums import Role
from app.models.core import AppUser, Workspace


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
    domain = normalize_email(email).split("@", 1)[1]
    return "WEB_" + hashlib.sha256(domain.encode("utf-8")).hexdigest()[:28]


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
    domain = normalize_email(email).split("@", 1)[1].split(".", 1)[0]
    return f"{domain.replace('-', ' ').title()} Workspace"[:255]


async def ensure_web_identity(
    session: AsyncSession, *, email: str, name: str | None = None, workspace: str | None = None
) -> tuple[Workspace, AppUser]:
    normalized_email = normalize_email(email)
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
