import uuid

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import IdempotencyDep, PageDep, PrincipalDep, SessionDep, requires
from app.core.errors import BankReconError, ErrorCode
from app.core.rbac import Action
from app.domain.enums import CaseState, MatchState, TransactionStatus
from app.models.cases import ExceptionCase
from app.models.core import BankTransaction, Reconciliation, Statement, TransactionMatch
from app.models.infra import AuditEvent
from app.schemas.api import (
    AuditEventOut,
    CreateReconciliation,
    ReconciliationDetail,
    ReconciliationSummary,
    StatementProvenance,
    TransactionPage,
)
from app.services import audit
from app.services.api_mapping import money, transaction_out
from app.services.ingestion.files import parse_ledger_csv, parse_signed_pdf
from app.services.ingestion.persistence import import_signed_sources
from app.services.matching.persistence import match_reconciliation

router = APIRouter(prefix="/reconciliations", tags=["reconciliations"])


@router.get("", response_model=list[ReconciliationSummary])
async def list_reconciliations(
    session: SessionDep, principal: PrincipalDep
) -> list[ReconciliationSummary]:
    rows = (
        await session.execute(
            select(Reconciliation)
            .where(Reconciliation.workspace_id == principal.workspace_id)
            .order_by(Reconciliation.period_start.desc())
        )
    ).scalars()
    return [await _summarise(session, r) for r in rows]


@router.post("", response_model=ReconciliationSummary, status_code=201)
async def create_reconciliation(
    body: CreateReconciliation,
    session: SessionDep,
    idempotency: IdempotencyDep,
    principal=requires(Action.UPLOAD_STATEMENT),
) -> ReconciliationSummary:
    existing = (
        await session.execute(
            select(Reconciliation).where(
                Reconciliation.workspace_id == principal.workspace_id,
                Reconciliation.account_last4 == body.account_last4,
                Reconciliation.period_start == body.period_start,
                Reconciliation.period_end == body.period_end,
                Reconciliation.currency == body.currency,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise BankReconError(
            ErrorCode.E_DUPLICATE_STATEMENT, date=existing.created_at.date().isoformat()
        )

    reconciliation = Reconciliation(
        workspace_id=principal.workspace_id,
        account_last4=body.account_last4,
        period_start=body.period_start,
        period_end=body.period_end,
        currency=body.currency,
        created_by=principal.user_id,
    )
    session.add(reconciliation)
    await session.flush()
    await audit.record(
        session,
        workspace_id=principal.workspace_id,
        action="RECONCILIATION_CREATED",
        actor_user_id=principal.user_id,
        reconciliation_id=reconciliation.id,
        detail={"idempotency_key": idempotency},
    )
    await session.commit()
    return await _summarise(session, reconciliation)


@router.post("/import", response_model=list[ReconciliationSummary], status_code=201)
async def import_reconciliation(
    session: SessionDep,
    idempotency: IdempotencyDep,
    principal=requires(Action.UPLOAD_STATEMENT),
    account_last4: str = Form(...),
    period_start: str = Form(...),
    period_end: str = Form(...),
    bank_file: UploadFile = File(...),
    ledger_file: UploadFile = File(...),
) -> list[ReconciliationSummary]:
    from datetime import date

    try:
        start = date.fromisoformat(period_start)
        end = date.fromisoformat(period_end)
    except ValueError as exc:
        raise BankReconError(
            ErrorCode.E_VALIDATION,
            detail="Use ISO dates for the reconciliation period.",
        ) from exc

    bank = parse_signed_pdf(
        await bank_file.read(),
        bank_file.filename or "statement.pdf",
    )
    ledger = parse_ledger_csv(
        await ledger_file.read(),
        ledger_file.filename or "ledger.csv",
    )

    ids = await import_signed_sources(
        session,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        account_last4=account_last4,
        start=start,
        end=end,
        bank=bank,
        ledger=ledger,
    )
    reconciliations: list[ReconciliationSummary] = []
    for reconciliation_id in ids:
        await match_reconciliation(
            session,
            reconciliation_id=reconciliation_id,
            workspace_id=principal.workspace_id,
        )
        reconciliation = await _load(session, reconciliation_id, principal.workspace_id)
        reconciliations.append(await _summarise(session, reconciliation))
    await audit.record(
        session,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action="WEB_IMPORT_COMPLETED",
        detail={"reconciliation_ids": [str(r.id) for r in reconciliations], "idempotency_key": idempotency},
    )
    await session.commit()
    return reconciliations


@router.get("/{reconciliation_id}", response_model=ReconciliationDetail)
async def get_reconciliation(
    reconciliation_id: uuid.UUID, session: SessionDep, principal: PrincipalDep
) -> ReconciliationDetail:
    reconciliation = await _load(session, reconciliation_id, principal.workspace_id)
    summary = await _summarise(session, reconciliation)

    statement = (
        await session.execute(
            select(Statement).where(Statement.reconciliation_id == reconciliation_id)
        )
    ).scalar_one_or_none()

    provenance = None
    if statement is not None:
        provenance = StatementProvenance(
            filename=statement.filename,
            content_sha256=statement.content_sha256,
            page_count=statement.page_count,
            extraction_method=str(statement.extraction_method),
            confidence=statement.confidence,
            inferred_date_format=statement.inferred_date_format,
            balance_breaks=statement.balance_breaks,
            skipped_rows=statement.skipped_rows,
            warnings=list(statement.warnings or []),
        )

    blockers = await completion_blockers(session, reconciliation_id)
    return ReconciliationDetail(
        **summary.model_dump(), statement=provenance, completion_blockers=blockers
    )


@router.get("/{reconciliation_id}/transactions", response_model=TransactionPage)
async def list_transactions(
    reconciliation_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
    page: PageDep,
    status: str | None = None,
    q: str | None = None,
) -> TransactionPage:
    await _load(session, reconciliation_id, principal.workspace_id)

    statement = select(BankTransaction).where(
        BankTransaction.reconciliation_id == reconciliation_id
    )
    if status:
        statement = statement.where(BankTransaction.status == status)
    if q:
        term = f"%{q.upper()}%"
        statement = statement.where(
            func.upper(BankTransaction.narration).like(term)
            | BankTransaction.reference_norm.like(term)
        )
    if page.cursor:
        statement = statement.where(BankTransaction.row_index > int(page.cursor))

    rows = list(
        (
            await session.execute(
                statement.order_by(BankTransaction.row_index).limit(page.limit + 1)
            )
        ).scalars()
    )
    has_more = len(rows) > page.limit
    rows = rows[: page.limit]
    return TransactionPage(
        items=[transaction_out(r) for r in rows],
        cursor={
            "next": str(rows[-1].row_index) if rows and has_more else None,
            "has_more": has_more,
        },
    )


@router.get("/{reconciliation_id}/audit", response_model=list[AuditEventOut])
async def list_audit_events(
    reconciliation_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
) -> list[AuditEventOut]:
    await _load(session, reconciliation_id, principal.workspace_id)
    rows = list(
        (
            await session.execute(
                select(AuditEvent)
                .where(
                    AuditEvent.workspace_id == principal.workspace_id,
                    AuditEvent.reconciliation_id == reconciliation_id,
                )
                .order_by(AuditEvent.created_at.desc())
                .limit(200)
            )
        ).scalars()
    )
    return [
        AuditEventOut(
            id=row.id,
            action=row.action,
            actor_user_id=row.actor_user_id,
            actor_slack_id=row.actor_slack_id,
            case_id=row.case_id,
            from_state=row.from_state,
            to_state=row.to_state,
            reason=row.reason,
            detail=dict(row.detail or {}),
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/{reconciliation_id}/audit.csv")
async def export_audit(
    reconciliation_id: uuid.UUID,
    session: SessionDep,
    principal=requires(Action.EXPORT_AUDIT),
) -> StreamingResponse:
    from app.services.audit_export import stream_audit_csv

    await _load(session, reconciliation_id, principal.workspace_id)
    return StreamingResponse(
        stream_audit_csv(session, reconciliation_id),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="audit-{reconciliation_id}.csv"'
        },
    )


async def _load(
    session, reconciliation_id: uuid.UUID, workspace_id: uuid.UUID
) -> Reconciliation:
    reconciliation = (
        await session.execute(
            select(Reconciliation).where(
                Reconciliation.id == reconciliation_id,
                Reconciliation.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if reconciliation is None:
        raise BankReconError(ErrorCode.E_NOT_FOUND, what="that reconciliation")
    return reconciliation


async def _count_by_status(session, reconciliation_id: uuid.UUID) -> dict[str, int]:
    rows = await session.execute(
        select(BankTransaction.status, func.count())
        .where(BankTransaction.reconciliation_id == reconciliation_id)
        .group_by(BankTransaction.status)
    )
    return {str(status): int(count) for status, count in rows}


async def _summarise(session, reconciliation: Reconciliation) -> ReconciliationSummary:
    counts = await _count_by_status(session, reconciliation.id)
    open_cases = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ExceptionCase)
                .where(
                    ExceptionCase.reconciliation_id == reconciliation.id,
                    ExceptionCase.state != CaseState.CLOSED,
                )
            )
        ).scalar_one()
    )
    at_risk = int(
        (
            await session.execute(
                select(func.coalesce(func.sum(ExceptionCase.value_at_risk_minor), 0)).where(
                    ExceptionCase.reconciliation_id == reconciliation.id,
                    ExceptionCase.state != CaseState.CLOSED,
                )
            )
        ).scalar_one()
    )

    return ReconciliationSummary(
        id=reconciliation.id,
        account_last4=reconciliation.account_last4,
        period_start=reconciliation.period_start,
        period_end=reconciliation.period_end,
        state=reconciliation.state,
        currency=reconciliation.currency,
        total_rows=sum(counts.values()),
        matched=counts.get(str(TransactionStatus.AUTO), 0)
        + counts.get(str(TransactionStatus.CONFIRMED), 0),
        review=counts.get(str(TransactionStatus.REVIEW), 0),
        in_case=counts.get(str(TransactionStatus.IN_CASE), 0),
        unmatched=counts.get(str(TransactionStatus.UNMATCHED), 0),
        open_cases=open_cases,
        value_at_risk=money(at_risk, reconciliation.currency),
        created_at=reconciliation.created_at,
        completed_at=reconciliation.completed_at,
    )


async def completion_blockers(session, reconciliation_id: uuid.UUID) -> list[str]:
    """PRD rule R1: the reasons a period cannot be declared closed, in plain words."""
    blockers: list[str] = []

    open_cases = list(
        (
            await session.execute(
                select(ExceptionCase).where(
                    ExceptionCase.reconciliation_id == reconciliation_id,
                    ExceptionCase.state != CaseState.CLOSED,
                )
            )
        ).scalars()
    )
    if open_cases:
        blockers.append(f"{len(open_cases)} case(s) are not closed")
    if any(c.type == "EXTRACTION_UNCERTAIN" for c in open_cases):
        blockers.append("an extraction-uncertain case is still open")

    undecided = int(
        (
            await session.execute(
                select(func.count())
                .select_from(TransactionMatch)
                .where(
                    TransactionMatch.reconciliation_id == reconciliation_id,
                    TransactionMatch.state == MatchState.REVIEW,
                )
            )
        ).scalar_one()
    )
    if undecided:
        blockers.append(f"{undecided} review-band match(es) are undecided")
    return blockers
