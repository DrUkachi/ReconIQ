from dataclasses import dataclass

from app.core.errors import BankReconError, ErrorCode
from app.domain.enums import CaseState, ReconciliationState

# PRD section 10. Prose lifecycles produce illegal states in code, so the guard
# tables are data and every transition is checked against them.


@dataclass(frozen=True)
class CaseGuardContext:
    has_assignee: bool = False
    has_pending_proposal: bool = False
    proposal_approved: bool = False
    reason: str | None = None
    agent_requested_info: bool = False
    assignee_replied: bool = False


# (from, to) -> the guard that must hold, expressed as a predicate name for errors.
CASE_TRANSITIONS: dict[tuple[CaseState, CaseState], str] = {
    (CaseState.OPEN, CaseState.ASSIGNED): "assignee_set",
    (CaseState.ASSIGNED, CaseState.AWAITING_INFO): "agent_requested_info",
    (CaseState.AWAITING_INFO, CaseState.ASSIGNED): "assignee_replied",
    (CaseState.ASSIGNED, CaseState.PROPOSED): "proposal_exists",
    (CaseState.AWAITING_INFO, CaseState.PROPOSED): "proposal_exists",
    (CaseState.PROPOSED, CaseState.RESOLVED): "proposal_approved",
    (CaseState.PROPOSED, CaseState.ASSIGNED): "always",
    (CaseState.RESOLVED, CaseState.CLOSED): "always",
    (CaseState.CLOSED, CaseState.REOPENED): "reason_required",
    (CaseState.REOPENED, CaseState.OPEN): "always",
    (CaseState.REOPENED, CaseState.ASSIGNED): "assignee_set",
}


def _guard_holds(guard: str, ctx: CaseGuardContext) -> bool:
    if guard == "always":
        return True
    if guard == "assignee_set":
        return ctx.has_assignee
    if guard == "agent_requested_info":
        return ctx.agent_requested_info
    if guard == "assignee_replied":
        return ctx.assignee_replied
    if guard == "proposal_exists":
        return ctx.has_pending_proposal
    if guard == "proposal_approved":
        return ctx.proposal_approved
    if guard == "reason_required":
        return bool(ctx.reason and ctx.reason.strip())
    return False


def is_legal_case_transition(from_state: CaseState, to_state: CaseState) -> bool:
    return (from_state, to_state) in CASE_TRANSITIONS


def check_case_transition(
    from_state: CaseState, to_state: CaseState, ctx: CaseGuardContext | None = None
) -> None:
    """Raise E_ILLEGAL_TRANSITION unless the edge exists and its guard holds."""
    ctx = ctx or CaseGuardContext()
    guard = CASE_TRANSITIONS.get((from_state, to_state))
    if guard is None:
        raise BankReconError(ErrorCode.E_ILLEGAL_TRANSITION, state=str(from_state))
    if not _guard_holds(guard, ctx):
        raise BankReconError(ErrorCode.E_ILLEGAL_TRANSITION, state=str(from_state))


@dataclass(frozen=True)
class CompletionBlockers:
    open_cases: int = 0
    undecided_reviews: int = 0
    extraction_uncertain_open: bool = False

    @property
    def clear(self) -> bool:
        return (
            self.open_cases == 0
            and self.undecided_reviews == 0
            and not self.extraction_uncertain_open
        )


RECONCILIATION_TRANSITIONS: dict[ReconciliationState, frozenset[ReconciliationState]] = {
    ReconciliationState.CREATED: frozenset(
        {ReconciliationState.EXTRACTING, ReconciliationState.CANCELLED, ReconciliationState.FAILED}
    ),
    ReconciliationState.EXTRACTING: frozenset(
        {ReconciliationState.MATCHING, ReconciliationState.CANCELLED, ReconciliationState.FAILED}
    ),
    ReconciliationState.MATCHING: frozenset(
        {
            ReconciliationState.AWAITING_ACTION,
            ReconciliationState.CANCELLED,
            ReconciliationState.FAILED,
        }
    ),
    ReconciliationState.AWAITING_ACTION: frozenset(
        {
            ReconciliationState.COMPLETE,
            ReconciliationState.CANCELLED,
            ReconciliationState.FAILED,
        }
    ),
    ReconciliationState.COMPLETE: frozenset(),
    ReconciliationState.CANCELLED: frozenset(),
    ReconciliationState.FAILED: frozenset(),
}


def check_reconciliation_transition(
    from_state: ReconciliationState,
    to_state: ReconciliationState,
    *,
    rows_extracted: int = 0,
    ledger_loaded: bool = False,
    blockers: CompletionBlockers | None = None,
    period: str = "this period",
) -> None:
    """PRD rule R1: COMPLETE is computed, never set manually.

    Refusing to declare a period closed while work is outstanding is a feature,
    not a safety net.
    """
    if to_state not in RECONCILIATION_TRANSITIONS.get(from_state, frozenset()):
        raise BankReconError(ErrorCode.E_ILLEGAL_TRANSITION, state=str(from_state))

    if to_state is ReconciliationState.MATCHING:
        if rows_extracted <= 0 or not ledger_loaded:
            raise BankReconError(ErrorCode.E_ILLEGAL_TRANSITION, state=str(from_state))

    if to_state is ReconciliationState.COMPLETE:
        resolved = blockers or CompletionBlockers()
        if not resolved.clear:
            raise BankReconError(
                ErrorCode.E_COMPLETION_BLOCKED,
                period=period,
                n=resolved.open_cases,
                m=resolved.undecided_reviews,
            )
