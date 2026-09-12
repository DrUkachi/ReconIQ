"""Run with python -m scripts.inspect_inputs; source files are opened read-only."""

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.core.errors import BankReconError
from app.services.ingestion.files import read_ledger_csv, read_signed_pdf
from app.services.ingestion.signed import prepare_matching_inputs


def summary(imported):
    totals = defaultdict(int)
    for row in imported.accepted:
        totals[row.currency] += row.signed_minor
    return {
        "accepted": len(imported.accepted), "rejected": len(imported.rejected),
        "currency_counts": dict(sorted(Counter(r.currency for r in imported.accepted).items())),
        "signed_totals": {c: f"{Decimal(v) / 100:.2f}" for c, v in sorted(totals.items())},
        "rejections": [asdict(row) for row in imported.rejected],
        "warnings": [
            {"source": asdict(row.source), "warnings": row.warnings}
            for row in imported.accepted if row.warnings
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--period-start", type=date.fromisoformat, required=True)
    parser.add_argument("--period-end", type=date.fromisoformat, required=True)
    parser.add_argument("--validation-pdf", type=Path)
    args = parser.parse_args()
    if args.period_start > args.period_end:
        parser.error("period-start must be on or before period-end")
    try:
        bank, ledger = read_signed_pdf(args.bank), read_ledger_csv(args.ledger)
        report = {"stage": "ingestion_only", "bank": summary(bank), "ledger": summary(ledger)}
        if not bank.rejected and not ledger.rejected:
            inputs = prepare_matching_inputs(bank, ledger, args.period_start, args.period_end)
            report["matching_input_counts"] = {
                c: {"bank": len(inputs.bank_by_currency.get(c, ())),
                    "ledger": len(inputs.ledger_by_currency.get(c, ()))}
                for c in sorted(inputs.bank_by_currency.keys() | inputs.ledger_by_currency.keys())
            }
            report["excluded_from_matching"] = [
                {"source": asdict(r.source), "date": r.transaction_date.isoformat(),
                 "reason": "zero_amount" if r.signed_minor == 0 else "outside_period"}
                for r in inputs.excluded
            ]
        if args.validation_pdf:
            report["separate_validation_fixture"] = summary(read_signed_pdf(args.validation_pdf))
        print(json.dumps(report, indent=2))
        return int(bool(bank.rejected or ledger.rejected))
    except BankReconError as exc:
        print(json.dumps({"code": exc.code, "message": str(exc)}))
        return 1
    except OSError as exc:
        print(json.dumps({"code": "E_FILE_NOT_VISIBLE", "message": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
