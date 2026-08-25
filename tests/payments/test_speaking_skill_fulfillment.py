"""Speaking Skill payment fulfillment (usage row, no plan gen, no exam_module)."""

from __future__ import annotations

from unittest.mock import patch
from uuid import UUID

import pytest

from app.payments import service
from app.payments.constants import SPEAKING_SKILL_SLUG
from app.payments.exceptions import PaymentAmountMismatchError, PaymentNotFoundError
from app.payments.schemas import SubscriptionOut

USER_ID = UUID("00000000-0000-4000-8000-0000000000a1")
PLAN_ID = UUID("00000000-0000-4000-8000-0000000000d5")
PAYMENT_ID = UUID("00000000-0000-4000-8000-0000000000e6")
SUB_ID = "sub_speaking_1"
ORDER_ID = "order_speaking_1"
PAY_ID = "pay_speaking_1"


def _speaking_plan() -> dict:
    return {
        "id": str(PLAN_ID),
        "slug": SPEAKING_SKILL_SLUG,
        "name": "Speaking Skill",
        "amount": 89900,
        "currency": "INR",
        "duration_days": 180,
        "is_active": False,
    }


def _created_speaking_payment(*, status: str = "created") -> dict:
    return {
        "id": str(PAYMENT_ID),
        "user_id": str(USER_ID),
        "plan_id": str(PLAN_ID),
        "status": status,
        "amount": 89900,
        "currency": "INR",
        "razorpay_order_id": ORDER_ID,
    }


def _usage_row(**overrides) -> dict:
    base = {
        "id": "usage_ss_1",
        "user_id": str(USER_ID),
        "subscription_id": SUB_ID,
        "plan_id": str(PLAN_ID),
        "exam_module": None,
        "mocks_granted": 1,
        "mocks_used": 0,
    }
    base.update(overrides)
    return base


def _sub_out() -> SubscriptionOut:
    return SubscriptionOut(
        is_active=True,
        plan_slug=SPEAKING_SKILL_SLUG,
        plan_name="Speaking Skill",
        status="active",
    )


def test_speaking_skill_confirm_creates_usage_without_plan_gen():
    usage_store: list[dict] = []

    def _ensure(**kwargs):
        assert kwargs["exam_module"] is None
        assert kwargs["mocks_granted"] == 1
        if usage_store:
            return usage_store[0]
        row = _usage_row(
            subscription_id=str(kwargs["subscription_id"]),
            plan_id=str(kwargs["plan_id"]),
            exam_module=kwargs.get("exam_module"),
            mocks_granted=int(kwargs.get("mocks_granted") or 1),
        )
        usage_store.append(row)
        return row

    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_created_speaking_payment(),
        ),
        patch(
            "app.payments.service.repository.list_subscriptions_for_payment",
            return_value=[],
        ),
        patch(
            "app.payments.service.repository.get_plan_by_id",
            return_value=_speaking_plan(),
        ),
        patch(
            "app.payments.service.repository.get_active_subscription",
            return_value=None,
        ),
        patch(
            "app.payments.service.repository.confirm_payment_paid_bundle",
            return_value={
                "already_paid": False,
                "subscription_id": SUB_ID,
                "user_id": str(USER_ID),
            },
        ),
        patch(
            "app.payments.service.repository.ensure_user_program_usage",
            side_effect=_ensure,
        ) as ensure,
        patch(
            "app.payments.service.get_subscription",
            return_value=_sub_out(),
        ),
        patch("app.payments.service.repository.invalidate_active_subscription_cache"),
        patch(
            "app.learning.service.schedule_personalized_plan_generation"
        ) as plan_gen,
    ):
        result = service.confirm_payment_paid(
            razorpay_order_id=ORDER_ID,
            razorpay_payment_id=PAY_ID,
            razorpay_signature="sig",
            user_id=USER_ID,
            captured_amount=89900,
        )

    assert result.plan_slug == SPEAKING_SKILL_SLUG
    ensure.assert_called_once()
    plan_gen.assert_not_called()
    assert usage_store[0]["mocks_granted"] == 1
    assert usage_store[0]["exam_module"] is None


def test_speaking_skill_early_heal_on_already_paid():
    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_created_speaking_payment(status="paid"),
        ),
        patch(
            "app.payments.service.repository.list_subscriptions_for_payment",
            return_value=[{"id": SUB_ID}],
        ),
        patch(
            "app.payments.service.repository.get_plan_by_id",
            return_value=_speaking_plan(),
        ),
        patch(
            "app.payments.service.repository.invalidate_active_subscription_cache"
        ),
        patch(
            "app.payments.service.repository.ensure_user_program_usage",
            return_value=_usage_row(),
        ) as ensure,
        patch(
            "app.payments.service.get_subscription",
            return_value=_sub_out(),
        ),
    ):
        service.confirm_payment_paid(
            razorpay_order_id=ORDER_ID,
            razorpay_payment_id=PAY_ID,
            user_id=USER_ID,
            captured_amount=89900,
        )
    ensure.assert_called_once()
    assert ensure.call_args.kwargs["exam_module"] is None
    assert ensure.call_args.kwargs["mocks_granted"] == 1


def test_speaking_skill_amount_mismatch_creates_no_usage():
    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_created_speaking_payment(),
        ),
        patch(
            "app.payments.service.repository.list_subscriptions_for_payment",
            return_value=[],
        ),
        patch(
            "app.payments.service.repository.get_plan_by_id",
            return_value=_speaking_plan(),
        ),
        patch(
            "app.payments.service.repository.get_active_subscription",
            return_value=None,
        ),
        patch(
            "app.payments.service.repository.ensure_user_program_usage"
        ) as ensure,
    ):
        with pytest.raises(PaymentAmountMismatchError):
            service.confirm_payment_paid(
                razorpay_order_id=ORDER_ID,
                razorpay_payment_id=PAY_ID,
                user_id=USER_ID,
                captured_amount=1,
            )
    ensure.assert_not_called()


def test_speaking_skill_missing_payment_creates_no_usage():
    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=None,
        ),
        patch(
            "app.payments.service.repository.ensure_user_program_usage"
        ) as ensure,
    ):
        with pytest.raises(PaymentNotFoundError):
            service.confirm_payment_paid(
                razorpay_order_id=ORDER_ID,
                razorpay_payment_id=PAY_ID,
                user_id=USER_ID,
                captured_amount=89900,
            )
    ensure.assert_not_called()
