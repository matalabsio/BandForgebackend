#!/usr/bin/env python3
"""Backfill an orphan Razorpay capture into BandForge payments + fulfillment.

Ops must supply --user-id and --plan-slug (Razorpay orders have no identity notes).

  PYTHONPATH=. .venv/bin/python scripts/backfill_payment.py \\
    --order-id order_xxx --user-id <uuid> --plan-slug premium_monthly

  PYTHONPATH=. .venv/bin/python scripts/backfill_payment.py \\
    --payment-id pay_xxx --user-id ... --plan-slug starter_monthly --apply

  PYTHONPATH=. .venv/bin/python scripts/backfill_payment.py \\
    --order-id order_xxx --suggest
"""

from __future__ import annotations

import argparse
import json
import sys
from uuid import UUID

from app.config import reload_settings
from app.payments.backfill import (
    BackfillError,
    backfill_orphan,
    suggest_from_razorpay,
)
from app.payments.exceptions import PaymentAmountMismatchError, PlanNotFoundError
from app.payments.razorpay_client import clear_client_cache, clear_credentials_probe


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill orphan Razorpay payment into Supabase + fulfill"
    )
    parser.add_argument("--order-id", default=None, help="Razorpay order_… id")
    parser.add_argument("--payment-id", default=None, help="Razorpay pay_… id")
    parser.add_argument("--user-id", default=None, help="BandForge users.id UUID")
    parser.add_argument("--plan-slug", default=None, help="e.g. premium_monthly")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write DB + fulfill (default: dry-run)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    parser.add_argument(
        "--suggest",
        action="store_true",
        help="Print Razorpay email/amount plan hints (no mutation)",
    )
    args = parser.parse_args()

    if not args.order_id and not args.payment_id:
        parser.error("Provide --order-id and/or --payment-id")

    reload_settings()
    clear_client_cache()
    clear_credentials_probe()

    if args.suggest:
        try:
            hint = suggest_from_razorpay(
                order_id=args.order_id, payment_id=args.payment_id
            )
        except BackfillError as exc:
            print(f"suggest failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            "email": hint.email,
            "contact": hint.contact,
            "amount": hint.amount,
            "currency": hint.currency,
            "matching_plan_slugs": hint.matching_plan_slugs,
            "note": "Hints only — pass --user-id and --plan-slug explicitly to backfill",
        }
        print(json.dumps(payload, indent=2))
        if not args.user_id or not args.plan_slug:
            return 0

    if not args.user_id or not args.plan_slug:
        parser.error("--user-id and --plan-slug are required (unless --suggest only)")

    try:
        user_id = UUID(args.user_id)
    except ValueError:
        print(f"Invalid --user-id: {args.user_id}", file=sys.stderr)
        return 1

    try:
        report = backfill_orphan(
            order_id=args.order_id,
            payment_id=args.payment_id,
            user_id=user_id,
            plan_slug=args.plan_slug,
            apply=args.apply,
        )
    except (BackfillError, PaymentAmountMismatchError, PlanNotFoundError) as exc:
        print(f"backfill failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"backfill failed: {exc}", file=sys.stderr)
        return 1

    data = report.to_dict()
    if args.json:
        print(json.dumps(data, default=str, indent=2))
    else:
        print(
            f"backfill apply={report.apply} action={report.action} "
            f"order={report.order_id} pay={report.payment_id} "
            f"local={report.local_payment_id or '-'} status={report.local_status or '-'} "
            f"inserted={report.inserted} fulfilled={report.fulfilled} "
            f"audited={report.audited}"
        )
        if report.razorpay:
            print(
                f"  razorpay amount={report.razorpay.get('amount')} "
                f"currency={report.razorpay.get('currency')} "
                f"email={report.razorpay.get('email')}"
            )

    return 1 if report.error else 0


if __name__ == "__main__":
    raise SystemExit(main())
