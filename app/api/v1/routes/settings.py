from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import IdempotencyDep, PrincipalDep, SessionDep, SettingsDep, requires
from app.core.errors import BankReconError, ErrorCode
from app.core.rbac import Action
from app.models.core import AppUser, Workspace
from app.schemas.api import RoleUpdate, SettingsOut, SettingsUpdate
from app.services import audit
from app.services.api_mapping import money

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
async def read_settings(
    session: SessionDep, principal: PrincipalDep, settings: SettingsDep
) -> SettingsOut:
    workspace = await _workspace(session, principal)
    return SettingsOut(
        approval_value_threshold=money(workspace.approval_value_threshold_minor),
        auto_match_threshold=settings.auto_match_threshold,
        review_floor=settings.review_floor,
        ambiguity_gap=settings.ambiguity_gap,
        date_window_days=settings.date_window_days,
        listener_threshold=settings.listener_threshold,
        recon_channel_id=workspace.recon_channel_id,
    )


@router.put("", response_model=SettingsOut)
async def update_settings(
    body: SettingsUpdate,
    session: SessionDep,
    settings: SettingsDep,
    idempotency: IdempotencyDep,
    principal=requires(Action.CHANGE_SETTINGS),
) -> SettingsOut:
    workspace = await _workspace(session, principal)
    if body.approval_value_threshold_minor is not None:
        workspace.approval_value_threshold_minor = body.approval_value_threshold_minor
    if body.recon_channel_id is not None:
        workspace.recon_channel_id = body.recon_channel_id

    await audit.record(
        session,
        workspace_id=principal.workspace_id,
        action="SETTINGS_UPDATED",
        actor_user_id=principal.user_id,
        detail=body.model_dump(exclude_none=True),
    )
    await session.commit()
    return await read_settings(session, principal, settings)


@router.put("/roles", response_model=SettingsOut)
async def update_role(
    body: RoleUpdate,
    session: SessionDep,
    settings: SettingsDep,
    idempotency: IdempotencyDep,
    principal=requires(Action.CHANGE_SETTINGS),
) -> SettingsOut:
    """Only an owner assigns roles, which is what keeps the approver set meaningful."""
    user = (
        await session.execute(
            select(AppUser).where(
                AppUser.workspace_id == principal.workspace_id,
                AppUser.slack_user_id == body.slack_user_id,
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise BankReconError(ErrorCode.E_USER_NOT_FOUND, slack_id=body.slack_user_id)

    previous = user.role
    user.role = body.role
    await audit.record(
        session,
        workspace_id=principal.workspace_id,
        action="ROLE_CHANGED",
        actor_user_id=principal.user_id,
        from_state=str(previous),
        to_state=str(body.role),
        detail={"slack_user_id": body.slack_user_id},
    )
    await session.commit()
    return await read_settings(session, principal, settings)


async def _workspace(session, principal) -> Workspace:
    workspace = (
        await session.execute(select(Workspace).where(Workspace.id == principal.workspace_id))
    ).scalar_one_or_none()
    if workspace is None:
        raise BankReconError(ErrorCode.E_NOT_FOUND, what="your workspace")
    return workspace
