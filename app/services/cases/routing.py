from enum import StrEnum

from app.domain.enums import CaseType


class CaseRoute(StrEnum):
    ACCOUNTS = "accounts"
    PAYMENTS = "payments"
    TREASURY = "treasury"


TEAM_LABELS: dict[CaseRoute, str] = {
    CaseRoute.ACCOUNTS: "Account Teams",
    CaseRoute.PAYMENTS: "Payments Operations",
    CaseRoute.TREASURY: "Treasury",
}

# What the agent reads to decide which team owns an exception (LLM call site L6).
# Edit these sentences to change how work is split; no rule table needs to change.
TEAM_RESPONSIBILITIES: dict[CaseRoute, str] = {
    CaseRoute.TREASURY: (
        "Bank relationship and cash position: bank fees, charges, commissions, levies, stamp "
        "duty and interest the bank applied; FX differences; and timing differences where a "
        "payment settled in the bank on a different date than it was booked."
    ),
    CaseRoute.PAYMENTS: (
        "Payment operations: money received or sent that has no matching ledger record, "
        "unidentified or unapplied customer receipts, payments booked in the ledger that never "
        "reached the bank, and duplicate or repeated bank postings."
    ),
    CaseRoute.ACCOUNTS: (
        "Accounting and data quality: amount mismatches between the bank and the ledger, a line "
        "that fits several ledger records, statement lines that could not be read reliably, and "
        "anything unexplained that needs investigation before another team can act."
    ),
}

# The rule fallback: used when the agent is unavailable or not confident enough to decide.
CASE_ROUTES: dict[CaseType, CaseRoute] = {
    CaseType.BANK_CHARGE_UNBOOKED: CaseRoute.TREASURY,
    CaseType.TIMING_DIFFERENCE: CaseRoute.TREASURY,
    CaseType.MISSING_LEDGER_RECORD: CaseRoute.PAYMENTS,
    CaseType.UNIDENTIFIED_CREDIT: CaseRoute.PAYMENTS,
    CaseType.MISSING_BANK_ENTRY: CaseRoute.PAYMENTS,
    CaseType.DUPLICATE_BANK_ENTRY: CaseRoute.PAYMENTS,
    CaseType.AMOUNT_MISMATCH: CaseRoute.ACCOUNTS,
    CaseType.AMBIGUOUS_MATCH: CaseRoute.ACCOUNTS,
    CaseType.EXTRACTION_UNCERTAIN: CaseRoute.ACCOUNTS,
    CaseType.UNMATCHED_TRANSACTION: CaseRoute.ACCOUNTS,
}


def channel_for_team(team: str, case_channels: dict | None, recon_channel_id: str | None) -> str | None:
    """The team's channel, or the reconciliation channel when none is configured."""
    return (case_channels or {}).get(str(team)) or recon_channel_id


def channel_for(
    case_type: str, case_channels: dict | None, recon_channel_id: str | None
) -> str | None:
    """The rule-table team's channel for a case type."""
    return channel_for_team(CASE_ROUTES[CaseType(case_type)], case_channels, recon_channel_id)
