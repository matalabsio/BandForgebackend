"""Unit tests for recoverability drill helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from app.payments.drill import DrillError, run_drill, soft_break_payment
from app.payments.schemas import SubscriptionOut

PAYMENT_ID = UUID("00000000-0000-4000-8000-0000000000c3")
ORDER_ID = "order_drill_test"
RZP_PAYMENT = "pay_drill_test"


def _paid_row() -> dict:
    return {
        "id": str(PAYMENT_ID),
        "status": "paid",
        "razorpay_order_id": ORDER_ID,
        "razorpay_payment_id": RZP_PAYMENT,
        "user_id": "00000000-0000-4000-8000-0000000000a1",
        "plan_id": "00000000-0000-4000-8000-0000000000b2",
    }


def _settings(**overrides):
    base = {
        "razorpay_key_id": "rzp_test_key",
        "app_env": "development",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_soft_break_dry_run_does_not_mutate():
    row = _paid_row()
    with patch(
        "app.payments.drill.repository.list_subscriptions_for_payment",
        return_value=[{"id": "sub1"}],
    ) as list_subs, patch(
        "app.payments.drill.repository.delete_subscriptions_for_payment"
    ) as delete_subs, patch(
        "app.payments.drill.repository.mark_payment_status"
    ) as mark:
        snap = soft_break_payment(payment=row, apply=False)
    assert snap.subscription_count == 1
    assert snap.status == "paid"
    delete_subs.assert_not_called()
    mark.assert_not_called()
    list_subs.assert_called_once()


def test_soft_break_apply_deletes_and_marks_created():
    row = _paid_row()
    broken = {**row, "status": "created"}
    with patch(
        "app.payments.drill.repository.delete_subscriptions_for_payment",
        return_value=1,
    ) as delete_subs, patch(
        "app.payments.drill.repository.mark_payment_status",
        return_value=broken,
    ) as mark, patch(
        "app.payments.drill.repository.list_subscriptions_for_payment",
        return_value=[],
    ), patch("app.payments.drill.payment_log"):
        snap = soft_break_payment(payment=row, apply=True)
    delete_subs.assert_called_once_with(payment_id=row["id"])
    mark.assert_called_once_with(payment_id=row["id"], status="created")
    assert snap.status == "created"
    assert snap.subscription_count == 0


def test_run_drill_requires_ack_flag():
    with pytest.raises(DrillError, match="i-understand-test-only"):
        run_drill(razorpay_order_id=ORDER_ID, apply=False)


def test_run_drill_refuses_live_keys():
    with patch(
        "app.payments.drill.get_settings",
        return_value=_settings(razorpay_key_id="rzp_live_abc"),
    ):
        with pytest.raises(DrillError, match="LIVE"):
            run_drill(
                razorpay_order_id=ORDER_ID,
                i_understand_test_only=True,
            )


def test_run_drill_apply_calls_soft_break_and_confirm():
    row = _paid_row()
    repaired = {**row, "status": "paid"}
    with (
        patch("app.payments.drill.get_settings", return_value=_settings()),
        patch(
            "app.payments.drill.repository.get_payment_by_order_id",
            side_effect=[row, repaired],
        ),
        patch(
            "app.payments.drill.repository.get_payment_by_razorpay_payment_id",
            return_value=None,
        ),
        patch(
            "app.payments.drill.soft_break_payment",
            return_value=SimpleNamespace(
                payment_id=str(PAYMENT_ID),
                status="created",
                razorpay_order_id=ORDER_ID,
                razorpay_payment_id=RZP_PAYMENT,
                subscription_count=0,
            ),
        ) as soft_break,
        patch(
            "app.payments.drill.service.confirm_payment_paid",
            return_value=SubscriptionOut(is_active=True),
        ) as confirm,
        patch(
            "app.payments.drill.repository.list_subscriptions_for_payment",
            return_value=[{"id": "sub1"}],
        ),
        patch("app.payments.drill.payment_log"),
    ):
        report = run_drill(
            razorpay_order_id=ORDER_ID,
            apply=True,
            i_understand_test_only=True,
        )
    soft_break.assert_called_once()
    confirm.assert_called_once_with(
        razorpay_order_id=ORDER_ID,
        razorpay_payment_id=RZP_PAYMENT,
    )
    assert report.soft_broke is True
    assert report.repaired is True
    assert report.error is None
