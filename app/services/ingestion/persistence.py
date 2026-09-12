"""Transactional source import. Callers own commit/rollback; no external calls."""

import uuid
from dataclasses import asdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BankReconError, ErrorCode
from app.core.rbac import Action, AuthzContext, require
from app.domain.enums import ExtractionMethod, ReconciliationState, Role
from app.models.core import AppUser, BankTransaction, PaymentRecordRow, Reconciliation, Statement, Workspace
from app.models.imports import SourceImport
from app.services import audit
from app.services.cases.guards import check_reconciliation_transition
from app.services.ingestion.signed import ImportResult, prepare_matching_inputs


async def import_signed_sources(
    session: AsyncSession, *, workspace_id: uuid.UUID, actor_user_id: uuid.UUID,
    account_last4: str, start: date, end: date, bank: ImportResult, ledger: ImportResult,
    channel_id: str | None = None,
) -> tuple[uuid.UUID, ...]:
    actor = (await session.execute(select(AppUser).where(
        AppUser.id == actor_user_id, AppUser.workspace_id == workspace_id,
    ))).scalar_one_or_none()
    if actor is None:
        raise BankReconError(ErrorCode.E_AUTHZ, names="workspace approvers")
    context = AuthzContext(role=Role(actor.role), actor_user_id=str(actor.id))
    require(Action.UPLOAD_STATEMENT, context)
    require(Action.LOAD_LEDGER, context)
    if len(account_last4) != 4 or not account_last4.isalnum():
        raise BankReconError(ErrorCode.E_VALIDATION, detail="Supply a four-character account identifier.")
    inputs = prepare_matching_inputs(bank, ledger, start, end)
    if not bank.accepted or not ledger.accepted:
        raise BankReconError(ErrorCode.E_VALIDATION, detail="Both source files must contain transactions.")
    currencies = sorted(inputs.bank_by_currency.keys() | inputs.ledger_by_currency.keys())
    if not currencies:
        raise BankReconError(ErrorCode.E_NO_RECORDS_FOR_PERIOD, period=f"{start} to {end}")
    # Serialize imports for this workspace, including creation where no recon row
    # yet exists to lock. The database constraints remain the final backstop.
    workspace = (await session.execute(select(Workspace).where(
        Workspace.id == workspace_id,
    ).with_for_update())).scalar_one()
    ids = []
    for currency in currencies:
        txns = inputs.bank_by_currency.get(currency, ())
        records = inputs.ledger_by_currency.get(currency, ())
        if not txns or not records:
            raise BankReconError(ErrorCode.E_VALIDATION, detail=f"Both sources need in-period {currency} rows.")
        reconciliation = (await session.execute(select(Reconciliation).where(
            Reconciliation.workspace_id == workspace_id,
            Reconciliation.account_last4 == account_last4,
            Reconciliation.period_start == start, Reconciliation.period_end == end,
            Reconciliation.currency == currency,
        ).with_for_update())).scalar_one_or_none()
        if reconciliation is not None:
            if channel_id is not None and reconciliation.slack_channel_id != channel_id:
                raise BankReconError(ErrorCode.E_VALIDATION, detail="This scope already exists outside this intake channel.")
            sources = list((await session.execute(select(SourceImport).where(
                SourceImport.reconciliation_id == reconciliation.id,
            ))).scalars())
            expected = {"bank": bank.accepted[0].source.sha256, "ledger": ledger.accepted[0].source.sha256}
            if {s.kind: s.content_sha256 for s in sources} != expected:
                raise BankReconError(
                    ErrorCode.E_VALIDATION,
                    detail="This account/period/currency already exists with different sources or an unfinished import.",
                )
            ids.append(reconciliation.id)
            continue
        prior = (await session.execute(select(Statement).where(
            Statement.workspace_id == workspace_id,
            Statement.content_sha256 == bank.accepted[0].source.sha256,
            Statement.currency == currency,
        ))).scalar_one_or_none()
        if prior is not None:
            raise BankReconError(ErrorCode.E_DUPLICATE_STATEMENT, date=prior.created_at.date().isoformat())
        reconciliation = Reconciliation(
            workspace_id=workspace_id, account_last4=account_last4,
            period_start=start, period_end=end, currency=currency, created_by=actor.id,
            state=ReconciliationState.CREATED, slack_channel_id=channel_id,
        )
        session.add(reconciliation)
        await session.flush()
        for kind, imported in (("bank", bank), ("ledger", ledger)):
            source = imported.accepted[0].source
            if any(r.source.sha256 != source.sha256 for r in imported.accepted):
                raise BankReconError(ErrorCode.E_VALIDATION, detail="Each import must have one source file.")
            session.add(SourceImport(
                reconciliation_id=reconciliation.id, kind=kind, filename=source.source_file,
                content_sha256=source.sha256, byte_size=imported.byte_size,
                raw_rows=[{"source": asdict(r.source), "warnings": list(r.warnings)} for r in imported.accepted],
            ))
        bank_source = bank.accepted[0].source
        session.add(Statement(
            workspace_id=workspace_id, reconciliation_id=reconciliation.id,
            filename=bank_source.source_file, content_sha256=bank_source.sha256,
            currency=currency, byte_size=bank.byte_size,
            page_count=max(r.source.page or 0 for r in bank.accepted),
            extraction_method=ExtractionMethod.TEXT_LAYER, confidence=100,
            inferred_date_format="YYYY-MM-DD", balance_breaks=0, skipped_rows=0,
            warnings=["signed_export_profile", "balances_not_supplied"], raw_pages={},
        ))
        bank_raw = {f"bank:{r.source.id}": r for r in bank.accepted}
        ledger_raw = {f"ledger:{r.source.id}": r for r in ledger.accepted}
        for txn in txns:
            raw = bank_raw[txn.id]
            _check_lengths(raw.reference or "", txn.reference_norm, txn.counterparty_norm)
            session.add(BankTransaction(
                id=uuid.uuid5(reconciliation.id, txn.id), reconciliation_id=reconciliation.id,
                row_index=txn.row_index, value_date=txn.value_date, narration=txn.narration,
                reference_raw=raw.reference or "", reference_norm=txn.reference_norm,
                counterparty_norm=txn.counterparty_norm, amount_minor=txn.amount_minor,
                direction=txn.direction, currency=currency, warnings=list(txn.warnings),
            ))
        for record in records:
            raw = ledger_raw[record.id]
            _check_lengths(raw.reference or "", raw.narration or "", record.reference_norm, record.counterparty_norm)
            session.add(PaymentRecordRow(
                id=uuid.uuid5(reconciliation.id, record.id), workspace_id=workspace_id,
                reconciliation_id=reconciliation.id, external_id=record.external_id,
                record_date=record.record_date, amount_minor=record.amount_minor,
                direction=record.direction, currency=currency, reference_raw=raw.reference or "",
                reference_norm=record.reference_norm, counterparty_raw=raw.narration or "",
                counterparty_norm=record.counterparty_norm,
            ))
        for target in (ReconciliationState.EXTRACTING, ReconciliationState.MATCHING):
            check_reconciliation_transition(
                ReconciliationState(reconciliation.state), target,
                rows_extracted=len(txns), ledger_loaded=True,
            )
            reconciliation.state = target
        await audit.record(
            session, workspace_id=workspace.id, actor_user_id=actor.id,
            reconciliation_id=reconciliation.id, action="SIGNED_SOURCES_IMPORTED",
            detail={"currency": currency, "bank_rows": len(txns), "ledger_rows": len(records),
                    "bank_sha256": bank_source.sha256, "ledger_sha256": ledger.accepted[0].source.sha256,
                    "profile": "signed_export_v1", "source_rows_retained": [len(bank.accepted), len(ledger.accepted)]},
        )
        ids.append(reconciliation.id)
    await session.flush()
    return tuple(ids)


def _check_lengths(*values: str) -> None:
    if any(len(value) > 255 for value in values):
        raise BankReconError(ErrorCode.E_VALIDATION, detail="A reference or counterparty exceeds 255 characters; it cannot be truncated safely.")
