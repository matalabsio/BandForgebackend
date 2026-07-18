#!/usr/bin/env python3
"""Reconcile recent Razorpay captures against Supabase fulfillment.

Dry-run (default) reports stuck states. Pass ``--apply`` to replay
``confirm_payment_paid`` for repairable candidates.

  PYTHONPATH=. .venv/bin/python scripts/reconcile_payments.py --hours 48
  PYTHONPATH=. .venv/bin/python scripts/reconcile_payments.py --hours 48 --apply
"""

from __future__ import annotations

import argparse
import json
import sys

from app.config import reload_settings
from app.payments.reconcile import run_reconcile
from app.payments.razorpay_client import clear_client_cache, clear_credentials_probe


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile Razorpay payments vs Supabase")
    parser.add_argument(
        "--hours",
        type=int,
        default=48,
        help="Lookback window in hours (default: 48)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply repairs via confirm_payment_paid (default: dry-run)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON report",
    )
    args = parser.parse_args()

    reload_settings()
    clear_client_cache()
    clear_credentials_probe()

    report = run_reconcile(hours=args.hours, apply=args.apply)
    data = report.to_dict()

    if args.json:
        print(json.dumps(data, default=str, indent=2))
    else:
        print(
            f"reconcile hours={report.hours} apply={report.apply} "
            f"rzp={report.scanned_razorpay} local={report.scanned_local} "
            f"candidates={len(report.candidates)} "
            f"applied_ok={report.applied_ok} errors={report.applied_errors}"
        )
        for c in report.candidates:
            line = (
                f"  {c.verdict:28} action={c.action:12} "
                f"order={c.razorpay_order_id or '-'} "
                f"pay={c.razorpay_payment_id or '-'} "
                f"status={c.local_status or '-'}"
            )
            if c.applied:
                line += " APPLIED"
            if c.error:
                line += f" error={c.error}"
            print(line)

    return 1 if report.applied_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
