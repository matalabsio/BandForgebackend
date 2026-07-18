"""Orphan payment backfill tests."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from app.payments.backfill import (
    BackfillError,
    backfill_orphan,
)
from app.payments.constants import EVENT_BACKFILL
from app.payments.exceptions import PaymentAmountMismatchError

USER_ID = UUID("00000000-0000-4000-8000-0000000000a1")
PLAN_ID = UUID("00000000-0000-4000-8000-0000000000b2")
PAYMENT_ROW_ID = UUID("00000000-0000-4000-8000-0000000000c3")


def _plan(**overrides):
    row = {
        "id": str(PLAN_ID),
        "slug": "premium_monthly",
        "name": "Premium",
        "amount": 99900,
        "currency": "INR",
        "duration_days": 30,
    }
    row.update(overrides)
    return row


def _rzp_order_payment(*, amount: int = 99900):
    order = {
        "id": "order_orphan",
        "status": "paid",
        "amount": amount,
        "currency": "INR",
    }
    payment = {
        "id": "pay_orphan",
        "order_id": "order_orphan",
        "status": "captured",
        "captured": True,
        "amount": amount,
        "currency": "INR",
        "email": "student@example.com",
    }
    return order, payment


@contextmanager
def _rzp_ready(order, payment):
    client = MagicMock()
    client.order.fetch.return_value = order
    client.payment.fetch.return_value = payment
    client.order.payments.return_value = {"items": [payment]}
    with (
        patch(
            "app.payments.backfill.razorpay_client.credentials_ready",
            return_value=True,
        ),
        patch("app.payments.backfill.razorpay_client._client", return_value=client),
    ):
        yield


def test_backfill_dry_run_does_not_mutate():
    order, payment = _rzp_order_payment()
    with (
        _rzp_ready(order, payment),
        patch("app.payments.backfill.repository.get_plan_by_slug", return_value=_plan()),
        patch(
            "app.payments.backfill.repository.get_payment_by_order_id", return_value=None
        ),
        patch("app.payments.backfill.repository.insert_payment") as insert,
        patch("app.payments.backfill.service.confirm_payment_paid") as confirm,
        patch("app.payments.backfill.repository.insert_payment_event") as audit,
    ):
        report = backfill_orphan(
            order_id="order_orphan",
            payment_id=None,
            user_id=USER_ID,
            plan_slug="premium_monthly",
            apply=False,
        )
    assert report.action == "dry_run"
    assert report.inserted is False
    assert report.fulfilled is False
    insert.assert_not_called()
    confirm.assert_not_called()
    audit.assert_not_called()


def test_backfill_apply_inserts_and_fulfills_with_audit():
    order, payment = _rzp_order_payment()
    with (
        _rzp_ready(order, payment),
        patch("app.payments.backfill.repository.get_plan_by_slug", return_value=_plan()),
        patch(
            "app.payments.backfill.repository.get_payment_by_order_id", return_value=None
        ),
        patch(
            "app.payments.backfill.repository.insert_payment",
            return_value={"id": str(PAYMENT_ROW_ID)},
        ) as insert,
        patch("app.payments.backfill.service.confirm_payment_paid") as confirm,
        patch(
            "app.payments.backfill.repository.insert_payment_event",
            return_value={"id": "evt_bf"},
        ) as audit,
        patch("app.payments.backfill.repository.mark_event_processed") as processed,
    ):
        report = backfill_orphan(
            order_id="order_orphan",
            payment_id="pay_orphan",
            user_id=USER_ID,
            plan_slug="premium_monthly",
            apply=True,
        )
    assert report.action == "insert_and_fulfill"
    assert report.inserted is True
    assert report.fulfilled is True
    assert report.audited is True
    insert.assert_called_once()
    confirm.assert_called_once()
    kwargs = confirm.call_args.kwargs
    assert kwargs["razorpay_order_id"] == "order_orphan"
    assert kwargs["razorpay_payment_id"] == "pay_orphan"
    assert kwargs["captured_amount"] == 99900
    audit.assert_called_once()
    assert audit.call_args.kwargs["event_type"] == EVENT_BACKFILL
    assert audit.call_args.kwargs["razorpay_event_id"] == "backfill:order_orphan"
    processed.assert_called_once_with("evt_bf")


def test_backfill_amount_mismatch_raises():
    order, payment = _rzp_order_payment(amount=49900)
    with (
        _rzp_ready(order, payment),
        patch("app.payments.backfill.repository.get_plan_by_slug", return_value=_plan()),
        patch(
            "app.payments.backfill.repository.get_payment_by_order_id", return_value=None
        ),
        patch("app.payments.backfill.repository.insert_payment") as insert,
        patch("app.payments.backfill.service.confirm_payment_paid") as confirm,
    ):
        with pytest.raises(PaymentAmountMismatchError):
            backfill_orphan(
                order_id="order_orphan",
                payment_id=None,
                user_id=USER_ID,
                plan_slug="premium_monthly",
                apply=True,
            )
    insert.assert_not_called()
    confirm.assert_not_called()


def test_backfill_existing_paid_skips_insert():
    order, payment = _rzp_order_payment()
    local = {
        "id": str(PAYMENT_ROW_ID),
        "status": "paid",
        "user_id": str(USER_ID),
        "razorpay_order_id": "order_orphan",
    }
    with (
        _rzp_ready(order, payment),
        patch("app.payments.backfill.repository.get_plan_by_slug", return_value=_plan()),
        patch(
            "app.payments.backfill.repository.get_payment_by_order_id",
            return_value=local,
        ),
        patch("app.payments.backfill.repository.insert_payment") as insert,
        patch("app.payments.backfill.service.confirm_payment_paid") as confirm,
        patch(
            "app.payments.backfill.repository.insert_payment_event",
            return_value={"id": "evt_bf"},
        ),
        patch("app.payments.backfill.repository.mark_event_processed"),
    ):
        report = backfill_orphan(
            order_id="order_orphan",
            payment_id=None,
            user_id=USER_ID,
            plan_slug="premium_monthly",
            apply=True,
        )
    assert report.action == "already_paid"
    insert.assert_not_called()
    confirm.assert_not_called()


def test_backfill_existing_created_fulfills_only():
    order, payment = _rzp_order_payment()
    local = {
        "id": str(PAYMENT_ROW_ID),
        "status": "created",
        "user_id": str(USER_ID),
        "razorpay_order_id": "order_orphan",
    }
    with (
        _rzp_ready(order, payment),
        patch("app.payments.backfill.repository.get_plan_by_slug", return_value=_plan()),
        patch(
            "app.payments.backfill.repository.get_payment_by_order_id",
            return_value=local,
        ),
        patch("app.payments.backfill.repository.insert_payment") as insert,
        patch("app.payments.backfill.service.confirm_payment_paid") as confirm,
        patch(
            "app.payments.backfill.repository.insert_payment_event",
            return_value={"id": "evt_bf"},
        ),
        patch("app.payments.backfill.repository.mark_event_processed"),
    ):
        report = backfill_orphan(
            order_id="order_orphan",
            payment_id="pay_orphan",
            user_id=USER_ID,
            plan_slug="premium_monthly",
            apply=True,
        )
    assert report.action == "fulfill_only"
    assert report.fulfilled is True
    insert.assert_not_called()
    confirm.assert_called_once()


def test_backfill_reject_uncaptured():
    order = {"id": "order_x", "status": "created", "amount": 99900, "currency": "INR"}
    payment = {
        "id": "pay_x",
        "order_id": "order_x",
        "status": "failed",
        "captured": False,
        "amount": 99900,
        "currency": "INR",
    }
    with _rzp_ready(order, payment):
        with pytest.raises(BackfillError, match="not captured"):
            backfill_orphan(
                order_id="order_x",
                payment_id="pay_x",
                user_id=USER_ID,
                plan_slug="premium_monthly",
                apply=False,
            )
