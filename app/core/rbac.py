from dataclasses import dataclass
from enum import StrEnum

from app.core.errors import BankReconError, ErrorCode
from app.domain.enums import ROLE_RANK, Role

# PRD section 04. Enforced in code at every call site, never in a prompt.
# The model never sees the RBAC decision: it proposes, code decides.


class Action(StrEnum):
    VIEW = "VIEW"
    ASK = "ASK"
    UPLOAD_STATEMENT = "UPLOAD_STATEMENT"
    LOAD_LEDGER = "LOAD_LEDGER"
    CREATE_CASE = "CREATE_CASE"
    ASSIGN_CASE = "ASSIGN_CASE"
    ADD_EVIDENCE = "ADD_EVIDENCE"
    CONFIRM_MATCH = "CONFIRM_MATCH"
    PROPOSE_RESOLUTION = "PROPOSE_RESOLUTION"
    APPROVE_RESOLUTION = "APPROVE_RESOLUTION"
    ESCALATE = "ESCALATE"
    REOPEN_CASE = "REOPEN_CASE"
    CHANGE_SETTINGS = "CHANGE_SETTINGS"
    EXPORT_AUDIT = "EXPORT_AUDIT"


@dataclass(frozen=True)
class AuthzContext:
    """Everything a role check may consult.

    actor_user_id is taken from the invocation context, never from model
    arguments, so the model cannot claim to be someone (PRD rule 2, section 07).
    """

    role: Role
    actor_user_id: str | None = None
    assignee_user_id: str | None = None
    target_user_id: str | None = None
    value_at_risk_minor: int = 0
    threshold_minor: int = 50_000_000


# Actions gated purely on role rank.
_MIN_ROLE: dict[Action, Role] = {
    Action.VIEW: Role.MEMBER,
    Action.ASK: Role.MEMBER,
    Action.CREATE_CASE: Role.MEMBER,
    Action.ADD_EVIDENCE: Role.MEMBER,
    Action.PROPOSE_RESOLUTION: Role.MEMBER,
    Action.ESCALATE: Role.MEMBER,
    Action.UPLOAD_STATEMENT: Role.APPROVER,
    Action.LOAD_LEDGER: Role.APPROVER,
    Action.CONFIRM_MATCH: Role.APPROVER,
    Action.REOPEN_CASE: Role.APPROVER,
    Action.EXPORT_AUDIT: Role.APPROVER,
    Action.CHANGE_SETTINGS: Role.OWNER,
}


def is_allowed(action: Action, ctx: AuthzContext) -> bool:
    if action is Action.ASSIGN_CASE:
        # A member may assign only to themselves.
        if ROLE_RANK[ctx.role] >= ROLE_RANK[Role.APPROVER]:
            return True
        return ctx.target_user_id is not None and ctx.target_user_id == ctx.actor_user_id

    if action is Action.APPROVE_RESOLUTION:
        if ctx.value_at_risk_minor >= ctx.threshold_minor:
            return ROLE_RANK[ctx.role] >= ROLE_RANK[Role.APPROVER]
        if ROLE_RANK[ctx.role] >= ROLE_RANK[Role.APPROVER]:
            return True
        # Below threshold a member may approve, but only their own assigned case.
        return ctx.actor_user_id is not None and ctx.actor_user_id == ctx.assignee_user_id

    minimum = _MIN_ROLE.get(action)
    if minimum is None:
        return False
    return ROLE_RANK[ctx.role] >= ROLE_RANK[minimum]


def require(action: Action, ctx: AuthzContext) -> None:
    """Raise the taxonomy error the caller should surface. Never changes state."""
    if is_allowed(action, ctx):
        return

    if (
        action is Action.APPROVE_RESOLUTION
        and ctx.value_at_risk_minor >= ctx.threshold_minor
        and ROLE_RANK[ctx.role] < ROLE_RANK[Role.APPROVER]
    ):
        raise BankReconError(
            ErrorCode.E_VALUE_THRESHOLD,
            amount=ctx.value_at_risk_minor,
            threshold=ctx.threshold_minor,
            approver="approver",
        )

    raise BankReconError(ErrorCode.E_AUTHZ, names=_who_can(action))


def _who_can(action: Action) -> str:
    if action is Action.CHANGE_SETTINGS:
        return "owners"
    if action in {Action.ASSIGN_CASE, Action.APPROVE_RESOLUTION}:
        return "approvers and owners"
    minimum = _MIN_ROLE.get(action, Role.OWNER)
    return {
        Role.MEMBER: "members, approvers and owners",
        Role.APPROVER: "approvers and owners",
        Role.OWNER: "owners",
    }[minimum]
