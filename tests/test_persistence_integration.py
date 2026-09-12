"""Real PostgreSQL checks; set RECONIQ_TEST_DATABASE_URL to a migrated test DB."""

import asyncio
import os
import uuid
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.errors import BankReconError, ErrorCode
from app.domain.enums import MatchMethod, MatchState, Role
from app.models import AuditEvent, BankTransaction, ExceptionCase, PaymentRecordRow, Reconciliation, SourceImport, Statement, TransactionMatch, Workspace, AppUser
from app.services.ingestion.files import read_ledger_csv, read_signed_pdf
from app.services.ingestion.persistence import import_signed_sources
from app.services.matching.persistence import match_reconciliation

URL = os.environ.get("RECONIQ_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="RECONIQ_TEST_DATABASE_URL is not set")
FIXTURES = Path(__file__).parent / "fixtures" / "signed_exports"
START, END = date(2026, 8, 1), date(2026, 8, 31)


@pytest.fixture(scope="module")
def inputs():
    return read_signed_pdf(FIXTURES / "Bank_Statement_Demo.pdf"), read_ledger_csv(FIXTURES / "General_Ledger_Demo.csv")


@pytest_asyncio.fixture
async def database():
    engine = create_async_engine(URL)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(connection, expire_on_commit=False) as session:
            workspace = Workspace(slack_team_id=f"TEST_{uuid.uuid4().hex[:20]}", name="Integration test")
            session.add(workspace)
            await session.flush()
            actor = AppUser(workspace_id=workspace.id, slack_user_id="TEST_OWNER", role=Role.OWNER)
            session.add(actor)
            await session.flush()
            yield session, workspace, actor
        await transaction.rollback()
    await engine.dispose()


async def ingest(database, inputs):
    session, workspace, actor = database
    return await import_signed_sources(
        session, workspace_id=workspace.id, actor_user_id=actor.id,
        account_last4="DEMO", start=START, end=END, bank=inputs[0], ledger=inputs[1],
    )


async def count(session, model):
    return await session.scalar(select(func.count()).select_from(model))


@pytest.mark.asyncio
async def test_import_match_and_replays_preserve_every_source_and_do_not_duplicate(database, inputs):
    session, workspace, _ = database
    ids = await ingest(database, inputs)
    assert len(ids) == 3
    sources = list((await session.scalars(select(SourceImport).where(SourceImport.reconciliation_id.in_(ids)))).all())
    assert len(sources) == 6
    assert sorted(len(s.raw_rows) for s in sources) == [52, 52, 52, 57, 57, 57]
    assert all(s.byte_size > 0 for s in sources)
    assert {r.currency for r in await session.scalars(select(Statement).where(Statement.reconciliation_id.in_(ids)))} == {"EUR", "NGN", "USD"}
    bank = list(await session.scalars(select(BankTransaction).where(BankTransaction.reconciliation_id.in_(ids))))
    ledger = list(await session.scalars(select(PaymentRecordRow).where(PaymentRecordRow.reconciliation_id.in_(ids))))
    assert (len(bank), len(ledger)) == (55, 52)
    assert all(START <= row.value_date <= END for row in bank)
    assert len([r for r in bank if r.reference_raw == "PAY-81123"]) == 2
    assert next(r for r in bank if r.reference_raw == "0007429105").reference_norm == "0007429105"
    original_amounts = {r.id: (r.amount_minor, r.direction) for r in ledger}
    summaries = [await match_reconciliation(session, reconciliation_id=rid, workspace_id=workspace.id) for rid in ids]
    assert all(s["state"] == "AWAITING_ACTION" for s in summaries)
    models = (Reconciliation, SourceImport, BankTransaction, PaymentRecordRow, TransactionMatch, ExceptionCase, AuditEvent)
    counts_before = [await count(session, model) for model in models]
    assert await ingest(database, inputs) == ids
    assert [await match_reconciliation(session, reconciliation_id=rid, workspace_id=workspace.id) for rid in ids] == summaries
    assert [await count(session, model) for model in models] == counts_before
    await session.refresh(ledger[0])
    assert {r.id: (r.amount_minor, r.direction) for r in ledger} == original_amounts
    matches = list(await session.scalars(select(TransactionMatch).where(TransactionMatch.reconciliation_id.in_(ids))))
    assert len({m.bank_transaction_id for m in matches}) == len(matches)
    assert len({m.payment_record_id for m in matches}) == len(matches)
    bank_currency = {r.id: r.currency for r in bank}
    ledger_currency = {r.id: r.currency for r in ledger}
    assert all(bank_currency[m.bank_transaction_id] == ledger_currency[m.payment_record_id] for m in matches)


@pytest.mark.asyncio
async def test_failed_caller_transaction_leaves_no_partial_import_or_match(database, inputs):
    session, workspace, _ = database
    before = [await count(session, m) for m in (Reconciliation, SourceImport, BankTransaction, AuditEvent)]
    with pytest.raises(RuntimeError, match="abort before commit"):
        async with session.begin_nested():
            ids = await ingest(database, inputs)
            await match_reconciliation(session, reconciliation_id=ids[0], workspace_id=workspace.id)
            raise RuntimeError("abort before commit")
    assert [await count(session, m) for m in (Reconciliation, SourceImport, BankTransaction, AuditEvent)] == before


@pytest.mark.asyncio
async def test_replacement_source_is_rejected_without_changing_prior_import(database, inputs):
    session, _, _ = database
    ids = await ingest(database, inputs)
    changed_ledger = replace(inputs[1], accepted=tuple(
        replace(r, source=replace(r.source, sha256="a" * 64)) for r in inputs[1].accepted
    ))
    with pytest.raises(BankReconError, match="different sources"):
        async with session.begin_nested():
            await ingest(database, (inputs[0], changed_ledger))
    assert await ingest(database, inputs) == ids


@pytest.mark.asyncio
async def test_database_role_and_workspace_are_checked(database, inputs):
    session, workspace, actor = database
    actor.role = Role.MEMBER
    await session.flush()
    with pytest.raises(BankReconError) as exc:
        await ingest(database, inputs)
    assert exc.value.code == ErrorCode.E_AUTHZ
    actor.role = Role.OWNER
    await session.flush()
    with pytest.raises(BankReconError) as exc:
        await import_signed_sources(
            session, workspace_id=uuid.uuid4(), actor_user_id=actor.id,
            account_last4="DEMO", start=START, end=END, bank=inputs[0], ledger=inputs[1],
        )
    assert exc.value.code == ErrorCode.E_AUTHZ
    ids = await ingest(database, inputs)
    with pytest.raises(BankReconError) as exc:
        await match_reconciliation(session, reconciliation_id=ids[0], workspace_id=uuid.uuid4())
    assert exc.value.code == ErrorCode.E_NOT_FOUND


@pytest.mark.asyncio
async def test_database_rejects_reusing_a_matched_row(database, inputs):
    session, workspace, _ = database
    rid = (await ingest(database, inputs))[0]
    await match_reconciliation(session, reconciliation_id=rid, workspace_id=workspace.id)
    match = (await session.scalars(select(TransactionMatch).where(TransactionMatch.reconciliation_id == rid))).one()
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(TransactionMatch(
                reconciliation_id=rid, bank_transaction_id=match.bank_transaction_id,
                payment_record_id=match.payment_record_id, score=100, method=MatchMethod.EXACT,
                state=MatchState.AUTO, breakdown={},
            ))
            await session.flush()


@pytest.mark.asyncio
async def test_worker_handler_runs_persisted_inputs_and_replays(database, inputs, monkeypatch):
    from app.core import db
    from app.services.jobs.handlers import run_matching

    session, workspace, _ = database
    rid = (await ingest(database, inputs))[0]
    connection = await session.connection()
    maker = async_sessionmaker(connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    monkeypatch.setattr(db, "get_sessionmaker", lambda: maker)
    job = SimpleNamespace(workspace_id=workspace.id, payload={"reconciliation_id": str(rid)})
    await run_matching(job)
    before = await count(session, TransactionMatch)
    await run_matching(job)
    assert await count(session, TransactionMatch) == before
    session.expire_all()
    recon = await session.get(Reconciliation, rid)
    assert recon.state == "AWAITING_ACTION"


@pytest.mark.asyncio
async def test_concurrent_imports_and_matches_are_serialized(inputs):
    # Independent connections must see committed setup. A unique workspace keeps
    # this test isolated without deleting append-only audit history afterward.
    engine = create_async_engine(URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker.begin() as session:
            workspace = Workspace(slack_team_id=f"CONCUR_{uuid.uuid4().hex[:20]}", name="Concurrency test")
            session.add(workspace)
            await session.flush()
            actor = AppUser(workspace_id=workspace.id, slack_user_id="TEST", role=Role.OWNER)
            session.add(actor)
            await session.flush()
            workspace_id, actor_id = workspace.id, actor.id

        async def import_once():
            async with maker.begin() as session:
                return await import_signed_sources(
                    session, workspace_id=workspace_id, actor_user_id=actor_id,
                    account_last4="DEMO", start=START, end=END, bank=inputs[0], ledger=inputs[1],
                )

        first, second = await asyncio.gather(import_once(), import_once())
        assert first == second

        async def match_once():
            async with maker.begin() as session:
                return await match_reconciliation(session, reconciliation_id=first[1], workspace_id=workspace_id)

        assert (await asyncio.gather(match_once(), match_once()))[0] == await match_once()
        async with maker() as session:
            assert await session.scalar(select(func.count()).select_from(Reconciliation).where(Reconciliation.workspace_id == workspace_id)) == 3
            assert await session.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.reconciliation_id == first[1], AuditEvent.action == "MATCHING_COMPLETED",
            )) == 1
    finally:
        await engine.dispose()
