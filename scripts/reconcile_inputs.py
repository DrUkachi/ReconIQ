"""Persist unchanged signed inputs and run the existing matcher locally.

DATABASE_URL selects the database. No Slack messages or LLM calls are made.
"""

import argparse
import asyncio
import json
import uuid
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.db import get_engine, get_sessionmaker
from app.core.errors import BankReconError
from app.domain.enums import Role
from app.models.core import AppUser, Workspace
from app.services.ingestion.files import read_ledger_csv, read_signed_pdf
from app.services.ingestion.persistence import import_signed_sources
from app.services.matching.persistence import match_reconciliation

DEMO_TEAM = "RECONIQ_LOCAL_DEMO"
DEMO_USER = "LOCAL_DEMO_OWNER"


async def demo_identity(session):
    await session.execute(insert(Workspace).values(
        id=uuid.uuid4(), slack_team_id=DEMO_TEAM, name="ReconIQ local synthetic demo",
    ).on_conflict_do_nothing(index_elements=[Workspace.slack_team_id]))
    workspace = (await session.execute(select(Workspace).where(Workspace.slack_team_id == DEMO_TEAM))).scalar_one()
    await session.execute(insert(AppUser).values(
        id=uuid.uuid4(), workspace_id=workspace.id, slack_user_id=DEMO_USER,
        display_name="Local demo owner", role=Role.OWNER,
    ).on_conflict_do_nothing(index_elements=[AppUser.workspace_id, AppUser.slack_user_id]))
    actor = (await session.execute(select(AppUser).where(
        AppUser.workspace_id == workspace.id, AppUser.slack_user_id == DEMO_USER,
    ))).scalar_one()
    return workspace.id, actor.id


async def run(args):
    bank, ledger = read_signed_pdf(args.bank), read_ledger_csv(args.ledger)
    try:
        async with get_sessionmaker()() as session:
            async with session.begin():
                workspace_id, actor_id = await demo_identity(session) if args.demo else (args.workspace_id, args.actor_id)
                ids = await import_signed_sources(
                    session, workspace_id=workspace_id, actor_user_id=actor_id,
                    account_last4=args.account_last4, start=args.period_start, end=args.period_end,
                    bank=bank, ledger=ledger,
                )
                summaries = [await match_reconciliation(
                    session, reconciliation_id=rid, workspace_id=workspace_id,
                ) for rid in ids]
        return {"workspace_id": str(workspace_id), "profile": "existing_deterministic_engine",
                "reconciliations": summaries}
    finally:
        await get_engine().dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--account-last4", required=True)
    parser.add_argument("--period-start", type=date.fromisoformat, required=True)
    parser.add_argument("--period-end", type=date.fromisoformat, required=True)
    parser.add_argument("--demo", action="store_true", help="Create/use an isolated synthetic demo workspace and owner")
    parser.add_argument("--workspace-id", type=uuid.UUID)
    parser.add_argument("--actor-id", type=uuid.UUID)
    args = parser.parse_args()
    if not args.demo and (args.workspace_id is None or args.actor_id is None):
        parser.error("Supply --demo or both --workspace-id and --actor-id")
    if args.demo and (args.workspace_id is not None or args.actor_id is not None):
        parser.error("--demo cannot be combined with workspace/actor IDs")
    try:
        print(json.dumps(asyncio.run(run(args)), indent=2))
    except BankReconError as exc:
        print(json.dumps(exc.to_payload()))
        return 1
    except OSError as exc:
        print(json.dumps({"code": "E_FILE_NOT_VISIBLE", "message": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
