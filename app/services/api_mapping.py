from app.domain.enums import CaseState, ResolutionStatus
from app.domain.money import format_minor
from app.models.cases import CaseEvidence, ExceptionCase, ResolutionProposal
from app.models.core import BankTransaction
from app.schemas.api import (
    CaseSummary,
    EvidenceOut,
    Money,
    ProposalOut,
    TransactionOut,
)

# One place that turns persisted rows into API shapes, so a money field can never
# reach the frontend as a bare integer with no currency or as a float.


def money(minor: int | None, currency: str = "NGN") -> Money:
    amount = minor or 0
    return Money(minor=amount, currency=currency, display=format_minor(amount, currency))


def transaction_out(row: BankTransaction) -> TransactionOut:
    return TransactionOut(
        id=row.id,
        row_index=row.row_index,
        value_date=row.value_date,
        narration=row.narration,
        reference=row.reference_norm,
        counterparty=row.counterparty_norm,
        amount=money(row.amount_minor, row.currency),
        direction=row.direction,
        status=row.status,
        balance=money(row.balance_minor, row.currency) if row.balance_minor is not None else None,
        warnings=list(row.warnings or []),
        resolution_status=row.resolution_status,
        resolved_at=row.resolved_at,
        resolution_note=row.resolution_note,
    )


def case_resolution_status(state: str) -> ResolutionStatus:
    """A case is Resolved once a confirmed resolution applied; everything before that is Pending."""
    return ResolutionStatus.RESOLVED if state in (CaseState.RESOLVED, CaseState.CLOSED) else ResolutionStatus.PENDING


def case_summary(case: ExceptionCase) -> CaseSummary:
    return CaseSummary(
        id=case.id,
        type=case.type,
        state=case.state,
        priority=case.priority,
        title=case.title,
        value_at_risk=money(case.value_at_risk_minor, case.currency),
        assignee_id=case.assignee_id,
        due_at=case.due_at,
        permalink=case.permalink,
        version=case.version,
        resolution_status=case_resolution_status(case.state),
        slack_channel_id=case.slack_channel_id,
    )


def evidence_out(row: CaseEvidence) -> EvidenceOut:
    return EvidenceOut(
        id=row.id,
        kind=str(row.kind),
        author_slack_id=row.author_slack_id,
        excerpt=row.excerpt,
        permalink=row.permalink,
        matched_on=list(row.matched_on or []),
        score=row.score,
        verified=row.verified,
        created_at=row.created_at,
    )


def proposal_out(row: ResolutionProposal, *, requires_approver: bool = False) -> ProposalOut:
    return ProposalOut(
        id=row.id,
        reason_code=row.reason_code,
        narrative=row.narrative,
        state=str(row.state),
        evidence_ids=[str(e) for e in (row.evidence_ids or [])],
        proposed_by=row.proposed_by,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        requires_approver=requires_approver,
    )
