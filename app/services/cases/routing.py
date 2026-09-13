from enum import StrEnum

from app.domain.enums import CaseType


class CaseRoute(StrEnum):
    ACCOUNTS = "accounts"
    PAYMENTS = "payments"
    TREASURY = "treasury"


# Which team owns each exception scenario. Keys of workspace.case_channels.
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


def channel_for(
    case_type: str, case_channels: dict | None, recon_channel_id: str | None
) -> str | None:
    """The owning team's channel, or the reconciliation channel when none is configured."""
    route = CASE_ROUTES[CaseType(case_type)]
    return (case_channels or {}).get(str(route)) or recon_channel_id
