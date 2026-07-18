"""Reconciliation job tests."""

from __future__ import annotations

from unittest.mock import patch
from uuid import UUID

from app.payments.reconcile import (
    VERDICT_CREATE_ROW,
    VERDICT_SUBSCRIPTION,
    VERDICT_VERIFY,
    run_reconcile,
)

USER_ID = UUID("00000000-0000-4000-8000-0000000000a1")
PLAN_ID = UUID("00000000-0000-4000-8000-0000000000b2")
PAYMENT_ID = UUID("00000000-0000-4000-8000-0000000000c3")


def _local_created(**overrides):
    row = {
        "id": str(PAYMENT_ID),
        "user_id": str(USER_ID),
        "plan_id": str(PLAN_ID),
        "status": "created",
        "amount": 49900,
        "currency": "INR",
        "razorpay_order_id": "order_stuck",
        "razorpay_payment_id": None,
    }
    row.update(overrides)
    return row


def test_reconcile_dry_run_classifies_and_does_not_apply():
    rzp_payments = [
        {
            "id": "pay_cap",
            "order_id": "order_stuck",
            "status": "captured",
            "captured": True,
            "amount": 49900,
        },
        {
            "id": "pay_orphan",
            "order_id": "order_orphan",
            "status": "captured",
            "captured": True,
            "amount": 49900,
        },
    ]
    local_created = [_local_created()]
    paid_missing = [
        {
            **_local_created(
                id="payrow2",
                status="paid",
                razorpay_order_id="order_nosub",
                razorpay_payment_id="pay_nosub",
            ),
        }
    ]

    with (
        patch("app.payments.reconcile.razorpay_client.credentials_ready", return_value=True),
        patch(
            "app.payments.reconcile.razorpay_client.list_recent_payments",
            return_value=rzp_payments,
        ),
        patch(
            "app.payments.reconcile.repository.list_payments_since",
            return_value=local_created,
        ),
        patch(
            "app.payments.reconcile.repository.list_paid_payments_missing_subscriptions",
            return_value=paid_missing,
        ),
        patch(
            "app.payments.reconcile.repository.get_payment_by_order_id",
            side_effect=lambda oid: (
                local_created[0]
                if oid == "order_stuck"
                else paid_missing[0]
                if oid == "order_nosub"
                else None
            ),
        ),
        patch(
            "app.payments.reconcile.repository.get_payment_by_razorpay_payment_id",
            return_value=None,
        ),
        patch(
            "app.payments.reconcile.repository.list_subscriptions_for_payment",
            return_value=[],
        ),
        patch("app.payments.reconcile.service.confirm_payment_paid") as confirm,
    ):
        report = run_reconcile(hours=24, apply=False)

    confirm.assert_not_called()
    verdicts = {c.verdict for c in report.candidates}
    assert VERDICT_VERIFY in verdicts
    assert VERDICT_CREATE_ROW in verdicts
    assert VERDICT_SUBSCRIPTION in verdicts
    assert all(not c.applied for c in report.candidates)


def test_reconcile_apply_calls_confirm_for_stuck_verify_only():
    rzp_payments = [
        {
            "id": "pay_cap",
            "order_id": "order_stuck",
            "status": "captured",
            "captured": True,
            "amount": 49900,
        },
        {
            "id": "pay_orphan",
            "order_id": "order_orphan",
            "status": "captured",
            "captured": True,
            "amount": 49900,
        },
    ]
    local_created = [
        _local_created(razorpay_payment_id="pay_cap"),
    ]

    with (
        patch("app.payments.reconcile.razorpay_client.credentials_ready", return_value=True),
        patch(
            "app.payments.reconcile.razorpay_client.list_recent_payments",
            return_value=rzp_payments,
        ),
        patch(
            "app.payments.reconcile.repository.list_payments_since",
            return_value=local_created,
        ),
        patch(
            "app.payments.reconcile.repository.list_paid_payments_missing_subscriptions",
            return_value=[],
        ),
        patch(
            "app.payments.reconcile.repository.get_payment_by_order_id",
            side_effect=lambda oid: local_created[0] if oid == "order_stuck" else None,
        ),
        patch(
            "app.payments.reconcile.repository.get_payment_by_razorpay_payment_id",
            return_value=None,
        ),
        patch(
            "app.payments.reconcile.repository.list_subscriptions_for_payment",
            return_value=[],
        ),
        patch("app.payments.reconcile.service.confirm_payment_paid") as confirm,
    ):
        report = run_reconcile(hours=24, apply=True)

    assert confirm.call_count == 1
    kwargs = confirm.call_args.kwargs
    assert kwargs["razorpay_order_id"] == "order_stuck"
    assert kwargs["razorpay_payment_id"] == "pay_cap"
    assert report.applied_ok == 1
    create_row = [c for c in report.candidates if c.verdict == VERDICT_CREATE_ROW]
    assert create_row
    assert create_row[0].applied is False
    assert create_row[0].action == "report_only"
