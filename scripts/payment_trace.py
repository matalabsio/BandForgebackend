#!/usr/bin/env python3
"""Build a PaymentTrace join for one Razorpay order or payment id.

Supabase owns access (payments + subscriptions). Razorpay owns money movement.
Use after every manual test checkout; attach JSON output to bug reports.

  PYTHONPATH=. .venv/bin/python scripts/payment_trace.py --order-id order_xxx
  PYTHONPATH=. .venv/bin/python scripts/payment_trace.py --payment-id pay_xxx
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.config import get_settings, reload_settings
from app.payments import razorpay_client, repository
from app.payments.constants import PAYMENT_CREATED, PAYMENT_PAID, SUBSCRIPTION_ACTIVE


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _active_sub(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    if str(row.get("status") or "") != SUBSCRIPTION_ACTIVE:
        return False
    expires = _parse_dt(row.get("expires_at"))
    if not expires:
        return False
    return expires > datetime.now(UTC)


def _fetch_razorpay(order_id: str | None, payment_id: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "available": False,
        "order": None,
        "payments": [],
        "error": None,
    }
    if not razorpay_client.credentials_ready():
        out["error"] = "credentials_not_ready"
        return out
    try:
        client = razorpay_client._client()
        if not order_id and payment_id:
            payment = client.payment.fetch(payment_id)
            order_id = payment.get("order_id")
            out["payments"] = [
                {
                    "id": payment.get("id"),
                    "status": payment.get("status"),
                    "captured": payment.get("captured"),
                    "amount": payment.get("amount"),
                    "order_id": order_id,
                }
            ]
        if order_id:
            order = client.order.fetch(order_id)
            out["order"] = {
                "id": order.get("id"),
                "status": order.get("status"),
                "amount": order.get("amount"),
                "amount_paid": order.get("amount_paid"),
                "currency": order.get("currency"),
                "receipt": order.get("receipt"),
                "notes": order.get("notes") or [],
            }
            if not out["payments"]:
                raw = client.order.payments(order_id)
                items = raw.get("items") if isinstance(raw, dict) else raw
                for p in items or []:
                    out["payments"].append(
                        {
                            "id": p.get("id"),
                            "status": p.get("status"),
                            "captured": p.get("captured"),
                            "amount": p.get("amount"),
                            "order_id": p.get("order_id"),
                        }
                    )
        out["available"] = True
    except Exception as exc:  # noqa: BLE001 — diagnostic script
        out["error"] = str(exc)
    return out


def _razorpay_captured(rzp: dict[str, Any]) -> bool:
    order = rzp.get("order") or {}
    if str(order.get("status") or "") == "paid":
        return True
    for p in rzp.get("payments") or []:
        if p.get("captured") is True or str(p.get("status") or "") in (
            "captured",
            "authorized",
        ):
            return True
    return False


def _classify(
    *,
    payment: dict[str, Any] | None,
    active_subscription: bool,
    rzp: dict[str, Any],
    webhook_secret_set: bool,
) -> tuple[str, str | None]:
    """Return (verdict, webhook_note)."""
    webhook_note = None if webhook_secret_set else "WEBHOOK_DISABLED"
    captured = _razorpay_captured(rzp)
    order_known = bool((rzp.get("order") or {}).get("id")) or captured

    if not payment:
        if order_known or captured:
            return "STUCK_AT_create_row_missing", webhook_note
        if rzp.get("error"):
            return "STUCK_AT_create_row_missing", webhook_note
        return "STUCK_AT_create_row_missing", webhook_note

    status = str(payment.get("status") or "")
    if status == PAYMENT_PAID and active_subscription and captured:
        return "OK", webhook_note
    if status == PAYMENT_PAID and active_subscription and not rzp.get("available"):
        # DB fulfillment OK; Razorpay fetch skipped/failed — still OK for access
        return "OK", webhook_note
    if status == PAYMENT_PAID and not active_subscription:
        return "STUCK_AT_subscription", webhook_note
    if captured and status == PAYMENT_CREATED:
        return "STUCK_AT_verify", webhook_note
    if status == PAYMENT_CREATED and not captured:
        return "STUCK_AT_checkout", webhook_note
    if captured and status not in (PAYMENT_PAID,):
        return "STUCK_AT_verify", webhook_note
    return f"STUCK_AT_unknown_status_{status or 'empty'}", webhook_note


def build_trace(*, order_id: str | None, payment_id: str | None) -> dict[str, Any]:
    settings = get_settings()
    webhook_secret_set = bool((settings.razorpay_webhook_secret or "").strip())

    payment: dict[str, Any] | None = None
    if order_id:
        payment = repository.get_payment_by_order_id(order_id)
    if payment is None and payment_id:
        payment = repository.get_payment_by_razorpay_payment_id(payment_id)

    if payment and not order_id:
        order_id = payment.get("razorpay_order_id")
    if payment and not payment_id:
        payment_id = payment.get("razorpay_payment_id")

    rzp = _fetch_razorpay(order_id, payment_id)
    if not order_id and rzp.get("order"):
        order_id = (rzp["order"] or {}).get("id")
    if not payment_id and rzp.get("payments"):
        payment_id = rzp["payments"][0].get("id")

    plan: dict[str, Any] | None = None
    if payment and payment.get("plan_id"):
        plan = repository.get_plan_by_id(payment["plan_id"])

    subs_for_payment: list[dict[str, Any]] = []
    active_for_user: dict[str, Any] | None = None
    if payment:
        subs_for_payment = repository.list_subscriptions_for_payment(payment["id"])
        try:
            active_for_user = repository.get_active_subscription(
                UUID(str(payment["user_id"]))
            )
        except (TypeError, ValueError):
            active_for_user = None

    events: list[dict[str, Any]] = []
    if order_id:
        events = repository.list_payment_events_for_order(order_id)
    if payment_id:
        by_pay = repository.list_payment_events_for_payment_id(payment_id)
        seen = {e.get("id") for e in events}
        for e in by_pay:
            if e.get("id") not in seen:
                events.append(e)

    active = _active_sub(active_for_user) or any(_active_sub(s) for s in subs_for_payment)
    verdict, webhook_note = _classify(
        payment=payment,
        active_subscription=active,
        rzp=rzp,
        webhook_secret_set=webhook_secret_set,
    )
    if verdict != "OK" and not webhook_secret_set and verdict == "STUCK_AT_verify":
        # Emphasize missing fail-safe when browser verify is the gap.
        webhook_note = "WEBHOOK_DISABLED"

    payment_row = None
    if payment:
        payment_row = {
            "id": payment.get("id"),
            "user_id": payment.get("user_id"),
            "plan_id": payment.get("plan_id"),
            "status": payment.get("status"),
            "amount": payment.get("amount"),
            "currency": payment.get("currency"),
            "razorpay_order_id": payment.get("razorpay_order_id"),
            "razorpay_payment_id": payment.get("razorpay_payment_id"),
            "created_at": payment.get("created_at"),
            "updated_at": payment.get("updated_at"),
        }

    subscription_row = None
    if subs_for_payment:
        subscription_row = subs_for_payment[0]
    elif active_for_user:
        subscription_row = {
            "id": active_for_user.get("id"),
            "status": active_for_user.get("status"),
            "starts_at": active_for_user.get("starts_at"),
            "expires_at": active_for_user.get("expires_at"),
            "payment_id": active_for_user.get("payment_id"),
            "note": "active_for_user_not_linked_to_this_payment_row",
        }

    return {
        "PaymentTrace": {
            "user_id": (payment or {}).get("user_id"),
            "plan_id": (payment or {}).get("plan_id") or (plan or {}).get("id"),
            "plan_slug": (plan or {}).get("slug"),
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id
            or (payment_row or {}).get("razorpay_payment_id"),
            "supabase_payment": payment_row,
            "supabase_subscription": subscription_row,
            "subscription_is_active": active,
            "verify": "NOT_AVAILABLE_USE_NETWORK_TAB",
            "webhook_events": events or None,
            "webhook": webhook_note
            if not events
            else {"note": webhook_note, "events": events},
            "razorpay": rzp,
            "verdict": verdict,
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="BandForge payment lifecycle trace")
    parser.add_argument("--order-id", default=None, help="Razorpay order_id (order_…)")
    parser.add_argument(
        "--payment-id", default=None, help="Razorpay payment_id (pay_…)"
    )
    parser.add_argument("--reload-env", action="store_true")
    args = parser.parse_args()

    if not args.order_id and not args.payment_id:
        parser.error("Provide --order-id and/or --payment-id")

    if args.reload_env:
        reload_settings()
        razorpay_client.clear_client_cache()
        razorpay_client.clear_credentials_probe()

    # Mark credentials ready if keys exist (script may run without uvicorn probe).
    settings = get_settings()
    if settings.razorpay_enabled and settings.razorpay_key_id and settings.razorpay_key_secret:
        ok, _ = razorpay_client.probe_credentials()
        razorpay_client.set_credentials_probe_result(ok)

    trace = build_trace(order_id=args.order_id, payment_id=args.payment_id)
    print(json.dumps(trace, indent=2, default=str), flush=True)
    verdict = trace["PaymentTrace"]["verdict"]
    print(f"\nverdict: {verdict}", file=sys.stderr, flush=True)
    return 0 if verdict == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
