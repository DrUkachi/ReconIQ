"""Verify the installed app and register an explicitly supplied workspace owner."""
import argparse
import asyncio
import json
import re
import urllib.parse
import urllib.request

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.domain.enums import Role
from app.models.core import AppUser, Workspace


def call(method, **params):
    request = urllib.request.Request("https://slack.com/api/" + method,
        data=urllib.parse.urlencode(params).encode(),
        headers={"Authorization": "Bearer " + get_settings().slack_bot_token})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.load(response)
        scopes = response.headers.get("x-oauth-scopes", "")
    if not data.get("ok"):
        raise RuntimeError(f"{method}: {data.get('error', 'unknown_error')}; needed: {data.get('needed', '')}")
    return data, scopes


async def configure(owner):
    if not re.fullmatch(r"[UW][A-Z0-9]+", owner):
        raise ValueError("Supply a Slack member ID starting with U or W.")
    auth, scopes = call("auth.test")
    user, _ = call("users.info", user=owner)
    user = user["user"]
    if user.get("team_id") != auth["team_id"] or user.get("is_bot") or user.get("deleted"):
        raise ValueError("The owner must be an active human member of this workspace.")
    settings = get_settings()
    async with get_sessionmaker()() as session, session.begin():
        workspace = await session.scalar(select(Workspace).where(Workspace.slack_team_id == auth["team_id"]).with_for_update())
        if not workspace:
            workspace = Workspace(slack_team_id=auth["team_id"], name=auth.get("team") or "ReconIQ")
            session.add(workspace)
            await session.flush()
        workspace.bot_token = settings.slack_bot_token
        workspace.bot_user_id = auth["user_id"]
        workspace.recon_channel_id = settings.slack_recon_channel_id
        workspace.uninstalled_at = None
        actor = await session.scalar(select(AppUser).where(AppUser.workspace_id == workspace.id, AppUser.slack_user_id == owner))
        if not actor:
            actor = AppUser(workspace_id=workspace.id, slack_user_id=owner)
            session.add(actor)
        actor.role = Role.OWNER
        actor.display_name = user.get("real_name") or user.get("name") or "Owner"
    print(json.dumps({"team_id": auth["team_id"], "bot_user_id": auth["user_id"], "owner_user_id": owner, "registered": True, "granted_scopes": scopes}))
    for channel in filter(None, [settings.slack_recon_channel_id, *settings.slack_evidence_channel_ids.split(",")]):
        try:
            data, _ = call("conversations.info", channel=channel)
            print(json.dumps({"channel_id": channel, "is_member": data["channel"].get("is_member"), "name": data["channel"].get("name")}))
        except RuntimeError as exc:
            print(str(exc))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    asyncio.run(configure(parser.parse_args().owner))
