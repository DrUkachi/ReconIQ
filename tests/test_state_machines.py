import itertools

import pytest

from app.core.errors import BankReconError, ErrorCode
from app.domain.enums import CaseState, ReconciliationState
from app.services.cases.guards import (
    CASE_TRANSITIONS,
    CaseGuardContext,
    CompletionBlockers,
    check_case_transition,
    check_reconciliation_transition,
)

PERMISSIVE = CaseGuardContext(
    has_assignee=True,
    has_pending_proposal=True,
    proposal_approved=True,
    reason="because",
    agent_requested_info=True,
    assignee_replied=True,
)


@pytest.mark.parametrize(
    ("from_state", "to_state"), list(itertools.product(list(CaseState), list(CaseState)))
)
def test_every_illegal_case_edge_is_rejected(from_state, to_state):
    """PRD section 20: exhaustive over the full transition matrix."""
    if (from_state, to_state) in CASE_TRANSITIONS:
        check_case_transition(from_state, to_state, PERMISSIVE)
        return
    with pytest.raises(BankReconError) as excinfo:
        check_case_transition(from_state, to_state, PERMISSIVE)
    assert excinfo.value.code is ErrorCode.E_ILLEGAL_TRANSITION


def test_assignment_requires_an_assignee():
    with pytest.raises(BankReconError):
        check_case_transition(CaseState.OPEN, CaseState.ASSIGNED, CaseGuardContext())


def test_proposal_is_required_before_proposed():
    with pytest.raises(BankReconError):
        check_case_transition(
            CaseState.ASSIGNED, CaseState.PROPOSED, CaseGuardContext(has_pending_proposal=False)
        )


def test_resolution_requires_an_approved_proposal():
    with pytest.raises(BankReconError):
        check_case_transition(
            CaseState.PROPOSED, CaseState.RESOLVED, CaseGuardContext(proposal_approved=False)
        )


def test_reopening_requires_a_reason():
    with pytest.raises(BankReconError):
        check_case_transition(CaseState.CLOSED, CaseState.REOPENED, CaseGuardContext(reason=" "))
    check_case_transition(
        CaseState.CLOSED, CaseState.REOPENED, CaseGuardContext(reason="wrong counterparty")
    )


def test_closed_is_terminal_except_for_reopening():
    for target in CaseState:
        if target is CaseState.REOPENED:
            continue
        with pytest.raises(BankReconError):
            check_case_transition(CaseState.CLOSED, target, PERMISSIVE)


def test_matching_requires_rows_and_a_ledger():
    with pytest.raises(BankReconError):
        check_reconciliation_transition(
            ReconciliationState.EXTRACTING,
            ReconciliationState.MATCHING,
            rows_extracted=0,
            ledger_loaded=True,
        )
    with pytest.raises(BankReconError):
        check_reconciliation_transition(
            ReconciliationState.EXTRACTING,
            ReconciliationState.MATCHING,
            rows_extracted=118,
            ledger_loaded=False,
        )
    check_reconciliation_transition(
        ReconciliationState.EXTRACTING,
        ReconciliationState.MATCHING,
        rows_extracted=118,
        ledger_loaded=True,
    )


def test_completion_is_blocked_and_lists_the_blockers():
    with pytest.raises(BankReconError) as excinfo:
        check_reconciliation_transition(
            ReconciliationState.AWAITING_ACTION,
            ReconciliationState.COMPLETE,
            blockers=CompletionBlockers(open_cases=6, undecided_reviews=9),
            period="March 2026",
        )
    assert excinfo.value.code is ErrorCode.E_COMPLETION_BLOCKED
    message = excinfo.value.message
    assert "March 2026" in message and "6" in message and "9" in message


def test_an_open_extraction_uncertain_case_alone_blocks_completion():
    with pytest.raises(BankReconError) as excinfo:
        check_reconciliation_transition(
            ReconciliationState.AWAITING_ACTION,
            ReconciliationState.COMPLETE,
            blockers=CompletionBlockers(extraction_uncertain_open=True),
        )
    assert excinfo.value.code is ErrorCode.E_COMPLETION_BLOCKED


def test_completion_succeeds_only_when_everything_is_clear():
    check_reconciliation_transition(
        ReconciliationState.AWAITING_ACTION,
        ReconciliationState.COMPLETE,
        blockers=CompletionBlockers(),
    )


def test_terminal_reconciliation_states_accept_nothing():
    for terminal in (
        ReconciliationState.COMPLETE,
        ReconciliationState.CANCELLED,
        ReconciliationState.FAILED,
    ):
        for target in ReconciliationState:
            with pytest.raises(BankReconError):
                check_reconciliation_transition(terminal, target)
