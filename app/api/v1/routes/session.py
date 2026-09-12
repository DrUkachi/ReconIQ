from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.deps import PrincipalDep, SessionDep
from app.core.errors import BankReconError, ErrorCode
from app.models.core import AppUser, Workspace
from app.schemas.api import LogoutOut, SessionLogin, SessionOut
from app.services.web_auth import ensure_web_identity, session_payload

router = APIRouter(prefix="/session", tags=["session"])


@router.get("", response_model=SessionOut)
async def read_session(
    session: SessionDep,
    principal: PrincipalDep,
) -> SessionOut:
    user = (
        await session.execute(select(AppUser).where(AppUser.id == principal.user_id))
    ).scalar_one_or_none()
    workspace = (
        await session.execute(select(Workspace).where(Workspace.id == principal.workspace_id))
    ).scalar_one_or_none()
    if user is None or workspace is None:
        raise BankReconError(ErrorCode.E_NOT_FOUND, what="your workspace")
    return SessionOut.model_validate(session_payload(workspace, user))


@router.post("/login", response_model=SessionOut)
async def login(
    body: SessionLogin,
    request: Request,
    session: SessionDep,
) -> SessionOut:
    workspace, user = await ensure_web_identity(
        session,
        email=body.email,
        name=body.name,
        workspace=body.workspace_name,
    )
    request.session["user_id"] = str(user.id)
    await session.commit()
    return SessionOut.model_validate(session_payload(workspace, user))


@router.post("/logout", response_model=LogoutOut)
async def logout(request: Request) -> LogoutOut:
    request.session.clear()
    return LogoutOut()
