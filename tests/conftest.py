import json
from datetime import date, datetime, timezone

import pytest

from app.domain.enums import Direction
from app.domain.records import BankTxn, MatchingResult, PaymentRecord


def d(day: int, month: int = 3, year: int = 2026) -> date:
    return date(year, month, day)


def dt(day: int, hour: int = 12, month: int = 3, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def txn(
    txn_id: str,
    *,
    amount: int,
    day: int,
    direction: Direction = Direction.CREDIT,
    ref: str = "",
    counterparty: str = "",
    narration: str = "",
    warnings: tuple[str, ...] = (),
) -> BankTxn:
    return BankTxn(
        id=txn_id,
        row_index=int(txn_id[1:]) if txn_id[1:].isdigit() else 0,
        value_date=d(day),
        narration=narration or f"TRF FROM {counterparty}" if counterparty else narration,
        amount_minor=amount,
        direction=direction,
        reference_norm=ref,
        counterparty_norm=counterparty,
        warnings=warnings,
    )


def rec(
    record_id: str,
    *,
    amount: int,
    day: int,
    direction: Direction = Direction.CREDIT,
    ref: str = "",
    counterparty: str = "",
) -> PaymentRecord:
    return PaymentRecord(
        id=record_id,
        record_date=d(day),
        amount_minor=amount,
        direction=direction,
        reference_norm=ref,
        counterparty_norm=counterparty,
        external_id=record_id,
    )


def serialise(result: MatchingResult) -> str:
    """Stable serialisation used by the determinism gate."""
    return json.dumps(
        {
            "matches": [
                {
                    "txn": m.txn_id,
                    "record": m.record_id,
                    "score": m.score,
                    "method": str(m.method),
                    "state": str(m.state),
                    "breakdown": m.breakdown.as_dict(),
                }
                for m in result.matches
            ],
            "unmatched_txns": list(result.unmatched_txn_ids),
            "unmatched_records": list(result.unmatched_record_ids),
            "ambiguous": list(result.ambiguous_txn_ids),
            "duplicates": [
                {"key": [g.key[0], g.key[1].isoformat(), g.key[2]], "txns": list(g.txn_ids)}
                for g in result.duplicate_groups
            ],
            "timing": {k: list(v) for k, v in sorted(result.timing_candidates.items())},
        },
        sort_keys=True,
    )


@pytest.fixture
def sample_book() -> tuple[list[BankTxn], list[PaymentRecord]]:
    """A small book exercising every matching path: exact, scored, duplicate,
    ambiguous, fee, unidentified credit, and a missing bank entry."""
    txns = [
        txn("T01", amount=8_500_000, day=3, ref="ZEN0325887711", counterparty="ADEOLA FARMS"),
        txn("T02", amount=1_200_000, day=4, ref="INV0041", counterparty="KOLA LOGISTICS"),
        txn("T03", amount=24_000_000, day=5, counterparty="MERIDIAN"),
        txn("T04", amount=550_00, day=6, direction=Direction.DEBIT, narration="SMS ALERT CHARGE"),
        txn("T05", amount=310_000, day=7),
        txn("T06", amount=990_000, day=8, ref="DUP77771", counterparty="ZENITH SUPPLY"),
        txn("T07", amount=990_000, day=8, ref="DUP77771", counterparty="ZENITH SUPPLY"),
    ]
    records = [
        rec("R01", amount=8_500_000, day=3, ref="ZEN0325887711", counterparty="ADEOLA FARMS"),
        rec("R02", amount=1_200_000, day=5, ref="INV0041", counterparty="KOLA LOGISTICS LTD"),
        rec("R03", amount=24_000_000, day=5, counterparty="MERIDIAN HOLDINGS"),
        rec("R04", amount=24_000_000, day=5, counterparty="MERIDIAN HOLDING"),
        rec("R09", amount=4_100_000, day=9, direction=Direction.DEBIT, ref="PAYOUT9"),
    ]
    return txns, records
