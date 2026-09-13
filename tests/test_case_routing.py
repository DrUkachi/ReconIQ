from app.domain.enums import CaseType
from app.services.cases.routing import CASE_ROUTES, CaseRoute, channel_for


def test_every_case_type_has_a_route():
    assert set(CASE_ROUTES) == set(CaseType)


def test_routes_follow_the_agreed_team_table():
    assert CASE_ROUTES == {
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


def test_channel_for_prefers_the_team_channel():
    channels = {"payments": "CPAY", "treasury": "CTRE", "accounts": "CACC"}
    assert channel_for("DUPLICATE_BANK_ENTRY", channels, "CRECON") == "CPAY"
    assert channel_for("TIMING_DIFFERENCE", channels, "CRECON") == "CTRE"
    assert channel_for("AMOUNT_MISMATCH", channels, "CRECON") == "CACC"


def test_channel_for_falls_back_to_the_reconciliation_channel():
    assert channel_for("TIMING_DIFFERENCE", {}, "CRECON") == "CRECON"
    assert channel_for("TIMING_DIFFERENCE", {"payments": "CPAY"}, "CRECON") == "CRECON"
    assert channel_for("TIMING_DIFFERENCE", None, None) is None
