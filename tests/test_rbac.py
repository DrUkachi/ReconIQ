import itertools

import pytest

from app.core.errors import BankReconError, ErrorCode
from app.core.rbac import Action, AuthzContext, is_allowed, require
from app.domain.enums import Role

THRESHOLD = 50_000_000

# PRD section 20: table-driven and exhaustive over every action x every role.
EXPECTED: dict[Action, dict[Role, bool]] = {
    Action.VIEW: {Role.MEMBER: True, Role.APPROVER: True, Role.OWNER: True},
    Action.ASK: {Role.MEMBER: True, Role.APPROVER: True, Role.OWNER: True},
    Action.CREATE_CASE: {Role.MEMBER: True, Role.APPROVER: True, Role.OWNER: True},
    Action.ADD_EVIDENCE: {Role.MEMBER: True, Role.APPROVER: True, Role.OWNER: True},
    Action.PROPOSE_RESOLUTION: {Role.MEMBER: True, Role.APPROVER: True, Role.OWNER: True},
    Action.ESCALATE: {Role.MEMBER: True, Role.APPROVER: True, Role.OWNER: True},
    Action.UPLOAD_STATEMENT: {Role.MEMBER: False, Role.APPROVER: True, Role.OWNER: True},
    Action.LOAD_LEDGER: {Role.MEMBER: False, Role.APPROVER: True, Role.OWNER: True},
    Action.CONFIRM_MATCH: {Role.MEMBER: False, Role.APPROVER: True, Role.OWNER: True},
    Action.REOPEN_CASE: {Role.MEMBER: False, Role.APPROVER: True, Role.OWNER: True},
    Action.EXPORT_AUDIT: {Role.MEMBER: False, Role.APPROVER: True, Role.OWNER: True},
    Action.CHANGE_SETTINGS: {Role.MEMBER: False, Role.APPROVER: False, Role.OWNER: True},
}


@pytest.mark.parametrize(
    ("action", "role"), list(itertools.product(EXPECTED.keys(), list(Role)))
)
def test_role_matrix_is_exhaustive(action, role):
    ctx = AuthzContext(role=role, threshold_minor=THRESHOLD)
    assert is_allowed(action, ctx) is EXPECTED[action][role]


def test_member_may_assign_only_to_themselves():
    self_assign = AuthzContext(role=Role.MEMBER, actor_user_id="u1", target_user_id="u1")
    other = AuthzContext(role=Role.MEMBER, actor_user_id="u1", target_user_id="u2")
    assert is_allowed(Action.ASSIGN_CASE, self_assign) is True
    assert is_allowed(Action.ASSIGN_CASE, other) is False


@pytest.mark.parametrize("role", [Role.APPROVER, Role.OWNER])
def test_approvers_may_assign_to_anyone(role):
    ctx = AuthzContext(role=role, actor_user_id="u1", target_user_id="u2")
    assert is_allowed(Action.ASSIGN_CASE, ctx) is True


def test_assignee_may_approve_their_own_case_below_threshold():
    ctx = AuthzContext(
        role=Role.MEMBER,
        actor_user_id="u1",
        assignee_user_id="u1",
        value_at_risk_minor=THRESHOLD - 1,
        threshold_minor=THRESHOLD,
    )
    assert is_allowed(Action.APPROVE_RESOLUTION, ctx) is True


def test_member_may_not_approve_a_case_they_do_not_own():
    ctx = AuthzContext(
        role=Role.MEMBER,
        actor_user_id="u1",
        assignee_user_id="u2",
        value_at_risk_minor=1,
        threshold_minor=THRESHOLD,
    )
    assert is_allowed(Action.APPROVE_RESOLUTION, ctx) is False


def test_value_threshold_blocks_the_assignee_and_names_the_reason():
    ctx = AuthzContext(
        role=Role.MEMBER,
        actor_user_id="u1",
        assignee_user_id="u1",
        value_at_risk_minor=THRESHOLD,
        threshold_minor=THRESHOLD,
    )
    assert is_allowed(Action.APPROVE_RESOLUTION, ctx) is False
    with pytest.raises(BankReconError) as excinfo:
        require(Action.APPROVE_RESOLUTION, ctx)
    assert excinfo.value.code is ErrorCode.E_VALUE_THRESHOLD


def test_approver_clears_the_threshold():
    ctx = AuthzContext(
        role=Role.APPROVER,
        actor_user_id="u9",
        assignee_user_id="u1",
        value_at_risk_minor=THRESHOLD * 10,
        threshold_minor=THRESHOLD,
    )
    assert is_allowed(Action.APPROVE_RESOLUTION, ctx) is True


def test_denial_names_who_can_instead_of_leaking_the_rule():
    with pytest.raises(BankReconError) as excinfo:
        require(Action.CHANGE_SETTINGS, AuthzContext(role=Role.APPROVER))
    assert excinfo.value.code is ErrorCode.E_AUTHZ
    assert "owners" in excinfo.value.message
