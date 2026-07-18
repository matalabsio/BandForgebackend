#!/usr/bin/env python3
"""Intentional soft-break → reconcile repair drill (Test mode only).

Uses an already-paid Test payment. Soft-breaks local state (status→created,
delete subscription for that payment_id), then repairs via confirm/reconcile.

  PYTHONPATH=. .venv/bin/python scripts/drill_reconcile_repair.py \\
    --order-id order_xxx --i-understand-test-only

  PYTHONPATH=. .venv/bin/python scripts/drill_reconcile_repair.py \\
    --payment-id pay_xxx --i-understand-test-only --apply
"""

from __future__ import annotations

import argparse
import json
import sys

from app.config import reload_settings
from app.payments.drill import DrillError, run_drill
from app.payments.razorpay_client import clear_client_cache, clear_credentials_probe


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Soft-break a paid Test payment then repair via reconcile"
    )
    parser.add_argument("--order-id", default=None, help="Razorpay order_… id")
    parser.add_argument("--payment-id", default=None, help="Razorpay pay_… id")
    parser.add_argument(
        "--hours",
        type=int,
        default=168,
        help="Reconcile lookback if confirm falls back (default: 168)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Mutate DB + repair (default: dry-run)",
    )
    parser.add_argument(
        "--i-understand-test-only",
        action="store_true",
        help="Required acknowledgement — Test keys / non-production only",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    args = parser.parse_args()

    reload_settings()
    clear_client_cache()
    clear_credentials_probe()

    try:
        report = run_drill(
            razorpay_payment_id=args.payment_id,
            razorpay_order_id=args.order_id,
            apply=args.apply,
            hours=args.hours,
            i_understand_test_only=args.i_understand_test_only,
        )
    except DrillError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(f"apply={report.apply} soft_broke={report.soft_broke} repaired={report.repaired}")
        print(f"before:       {report.before}")
        print(f"after_break:  {report.after_break}")
        print(f"after_repair: {report.after_repair}")
        if report.error:
            print(f"error: {report.error}", file=sys.stderr)

    if args.apply and not report.repaired:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
