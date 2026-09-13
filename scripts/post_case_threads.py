"""Backfill: give every unexplained line a case, then post each unresolved case to its team channel.

    python -m scripts.post_case_threads --dry-run   # report only, writes nothing
    python -m scripts.post_case_threads             # create cases and queue the Slack threads

The worker's outbox dispatcher sends the queued messages and records each case's thread.
Safe to rerun: cases already posted or already owning a line are skipped.
"""
import argparse
import asyncio
import json
from datetime import timedelta

from sqlalchemy import exists, select

from app.core.db import get_sessionmaker
from app.domain.enums import CaseType, ReconciliationState, TransactionStatus
from app.models.base import utcnow
from app.models.cases import CaseMatchKey, CaseTransaction, ExceptionCase
from app.models.core import BankTransaction, Reconciliation, Workspace
from app.services import audit
from app.services.cases.slack_threads import enqueue_case_threads
from app.services.exceptions.engine import (
    PRIORITY_DUE_HOURS,
    UNMATCHED_SUMMARY,
    _txn_match_keys,
    assign_priority,
    unmatched_title,
)


async def backfill(dry_run: bool) -> dict:
    report = {"unmatched_cases_created": 0, "threads_queued": 0, "workspaces": []}
    async with get_sessionmaker()() as session:
        transaction = await session.begin()
        orphans = (await session.execute(
            select(BankTransaction, Reconciliation, Workspace)
            .join(Reconciliation, Reconciliation.id == BankTransaction.reconciliation_id)
            .join(Workspace, Workspace.id == Reconciliation.workspace_id)
            .where(
                Reconciliation.state == ReconciliationState.AWAITING_ACTION,
                BankTransaction.status == TransactionStatus.UNMATCHED,
                ~exists().where(CaseTransaction.bank_transaction_id == BankTransaction.id),
            )
            .order_by(BankTransaction.reconciliation_id, BankTransaction.row_index)
        )).all()
        for txn, reconciliation, workspace in orphans:
            case_type = CaseType.UNMATCHED_TRANSACTION
            priority = assign_priority(case_type, txn.amount_minor, workspace.approval_value_threshold_minor)
            case = ExceptionCase(
                workspace_id=workspace.id, reconciliation_id=reconciliation.id, type=case_type,
                priority=priority, title=unmatched_title(txn.direction, txn.amount_minor, txn.currency),
                summary=UNMATCHED_SUMMARY, value_at_risk_minor=txn.amount_minor, currency=txn.currency,
                due_at=utcnow() + timedelta(hours=PRIORITY_DUE_HOURS[priority]),
            )
            session.add(case)
            await session.flush()
            session.add(CaseTransaction(case_id=case.id, bank_transaction_id=txn.id))
            txn.status = TransactionStatus.IN_CASE
            for key_type, value in _txn_match_keys([txn]):
                session.add(CaseMatchKey(case_id=case.id, key_type=key_type, key_value=value))
            await audit.record(
                session, workspace_id=workspace.id, reconciliation_id=reconciliation.id, case_id=case.id,
                action="CASE_CREATED", detail={"type": str(case_type), "source": "backfill"},
            )
            report["unmatched_cases_created"] += 1
        await session.flush()

        workspaces = (await session.execute(select(Workspace).where(
            Workspace.bot_token.is_not(None), Workspace.bot_token != "", Workspace.uninstalled_at.is_(None),
        ))).scalars().all()
        for workspace in workspaces:
            queued = await enqueue_case_threads(session, workspace_id=workspace.id)
            report["threads_queued"] += queued
            report["workspaces"].append({"name": workspace.name, "threads_queued": queued,
                                         "case_channels": workspace.case_channels or {}})
        if dry_run:
            await transaction.rollback()
        else:
            await transaction.commit()
    report["dry_run"] = dry_run
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    print(json.dumps(asyncio.run(backfill(parser.parse_args().dry_run)), indent=2))
