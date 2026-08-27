"""Dual Bundle payment fulfillment (one sub, two skill-scoped usage rows)."""

from __future__ import annotations

from unittest.mock import patch
from uuid import UUID

from app.payments import service
from app.payments.constants import (
    DUAL_BUNDLE_SLUG,
    PROGRAM_SKILL_SPEAKING,
    PROGRAM_SKILL_WRITING,
    SPEAKING_SKILL_SLUG,
    WRITING_SKILL_SLUG,
)
from app.payments.schemas import SubscriptionOut

USER_ID = UUID("00000000-0000-4000-8000-0000000000a1")
DUAL_PLAN_ID = UUID("00000000-0000-4000-8000-0000000000d7")
WRITING_PLAN_ID = UUID("00000000-0000-4000-8000-0000000000d4")
SPEAKING_PLAN_ID = UUID("00000000-0000-4000-8000-0000000000d5")
PAYMENT_ID = UUID("00000000-0000-4000-8000-0000000000e7")
SUB_ID = "sub_dual_1"
ORDER_ID = "order_dual_1"
PAY_ID = "pay_dual_1"


def _dual_plan() -> dict:
    return {
        "id": str(DUAL_PLAN_ID),
        "slug": DUAL_BUNDLE_SLUG,
        "name": "Dual Bundle",
        "amount": 179900,
        "currency": "INR",
        "duration_days": 180,
        "is_active": False,
    }


def _writing_plan() -> dict:
    return {
        "id": str(WRITING_PLAN_ID),
        "slug": WRITING_SKILL_SLUG,
        "name": "Writing Skill",
        "amount": 89900,
        "is_active": True,
    }


def _speaking_plan() -> dict:
    return {
        "id": str(SPEAKING_PLAN_ID),
        "slug": SPEAKING_SKILL_SLUG,
        "name": "Speaking Skill",
        "amount": 89900,
        "is_active": True,
    }


def _created_dual_payment(*, status: str = "created") -> dict:
    return {
        "id": str(PAYMENT_ID),
        "user_id": str(USER_ID),
        "plan_id": str(DUAL_PLAN_ID),
        "status": status,
        "amount": 179900,
        "currency": "INR",
        "razorpay_order_id": ORDER_ID,
    }


def test_dual_bundle_confirm_creates_two_skill_usages():
    usage_store: dict[str, dict] = {}

    def _ensure(**kwargs):
        skill = str(kwargs["skill"])
        if skill in usage_store:
            return usage_store[skill]
        row = {
            "id": f"usage_{skill}",
            "user_id": str(USER_ID),
            "subscription_id": str(kwargs["subscription_id"]),
            "plan_id": str(kwargs["plan_id"]),
            "skill": skill,
            "exam_module": kwargs.get("exam_module"),
            "mocks_granted": int(kwargs.get("mocks_granted") or 1),
            "mocks_used": 0,
        }
        usage_store[skill] = row
        return row

    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_created_dual_payment(),
        ),
        patch(
            "app.payments.service.repository.list_subscriptions_for_payment",
            return_value=[],
        ),
        patch(
            "app.payments.service.repository.get_plan_by_id",
            return_value=_dual_plan(),
        ),
        patch(
            "app.payments.service.repository.get_plan_row_by_slug",
            side_effect=lambda slug: {
                WRITING_SKILL_SLUG: _writing_plan(),
                SPEAKING_SKILL_SLUG: _speaking_plan(),
            }.get(slug),
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
            "app.payments.service.repository.get_user_exam_module",
            return_value="academic",
        ),
        patch(
            "app.payments.service.repository.ensure_user_program_usage",
            side_effect=_ensure,
        ),
        patch(
            "app.payments.service.get_subscription",
            return_value=SubscriptionOut(
                is_active=True,
                plan_slug=DUAL_BUNDLE_SLUG,
                plan_name="Dual Bundle",
            ),
        ),
        patch("app.payments.service.repository.invalidate_active_subscription_cache"),
        patch(
            "app.learning.service.schedule_personalized_plan_generation"
        ) as sched,
    ):
        result = service.confirm_payment_paid(
            razorpay_order_id=ORDER_ID,
            razorpay_payment_id=PAY_ID,
            captured_amount=179900,
        )

    assert result.is_active
    assert result.plan_slug == DUAL_BUNDLE_SLUG
    assert set(usage_store) == {PROGRAM_SKILL_WRITING, PROGRAM_SKILL_SPEAKING}
    assert usage_store[PROGRAM_SKILL_WRITING]["plan_id"] == str(WRITING_PLAN_ID)
    assert usage_store[PROGRAM_SKILL_SPEAKING]["plan_id"] == str(SPEAKING_PLAN_ID)
    assert usage_store[PROGRAM_SKILL_WRITING]["mocks_granted"] == 1
    assert usage_store[PROGRAM_SKILL_SPEAKING]["mocks_granted"] == 1
    assert usage_store[PROGRAM_SKILL_WRITING]["exam_module"] == "academic"
    assert usage_store[PROGRAM_SKILL_SPEAKING]["exam_module"] is None
    assert usage_store[PROGRAM_SKILL_WRITING]["subscription_id"] == SUB_ID
    assert usage_store[PROGRAM_SKILL_SPEAKING]["subscription_id"] == SUB_ID
    sched.assert_not_called()


def test_dual_bundle_fulfillment_is_idempotent():
    ensure_calls: list[dict] = []
    usage_store: dict[str, dict] = {}

    def _ensure(**kwargs):
        ensure_calls.append(dict(kwargs))
        skill = str(kwargs["skill"])
        if skill in usage_store:
            return usage_store[skill]
        row = {
            "id": f"usage_{skill}",
            "subscription_id": str(kwargs["subscription_id"]),
            "plan_id": str(kwargs["plan_id"]),
            "skill": skill,
            "mocks_granted": 1,
            "mocks_used": 0,
            "exam_module": kwargs.get("exam_module"),
        }
        usage_store[skill] = row
        return row

    patches = (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_created_dual_payment(),
        ),
        patch(
            "app.payments.service.repository.list_subscriptions_for_payment",
            return_value=[],
        ),
        patch(
            "app.payments.service.repository.get_plan_by_id",
            return_value=_dual_plan(),
        ),
        patch(
            "app.payments.service.repository.get_plan_row_by_slug",
            side_effect=lambda slug: {
                WRITING_SKILL_SLUG: _writing_plan(),
                SPEAKING_SKILL_SLUG: _speaking_plan(),
            }.get(slug),
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
            "app.payments.service.repository.get_user_exam_module",
            return_value=None,
        ),
        patch(
            "app.payments.service.repository.ensure_user_program_usage",
            side_effect=_ensure,
        ),
        patch(
            "app.payments.service.get_subscription",
            return_value=SubscriptionOut(
                is_active=True,
                plan_slug=DUAL_BUNDLE_SLUG,
                plan_name="Dual Bundle",
            ),
        ),
        patch("app.payments.service.repository.invalidate_active_subscription_cache"),
        patch("app.learning.service.schedule_personalized_plan_generation"),
    )

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[
        5
    ], patches[6], patches[7], patches[8], patches[9], patches[10]:
        service.confirm_payment_paid(
            razorpay_order_id=ORDER_ID,
            razorpay_payment_id=PAY_ID,
            captured_amount=179900,
        )

    first_count = len(ensure_calls)
    assert first_count == 2

    # Second confirm: already paid + existing sub — heal path must not inflate quota.
    paid = _created_dual_payment(status="paid")
    existing_sub = {"id": SUB_ID, "payment_id": str(PAYMENT_ID)}
    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=paid,
        ),
        patch(
            "app.payments.service.repository.list_subscriptions_for_payment",
            return_value=[existing_sub],
        ),
        patch(
            "app.payments.service.repository.get_plan_by_id",
            return_value=_dual_plan(),
        ),
        patch(
            "app.payments.service.repository.get_plan_row_by_slug",
            side_effect=lambda slug: {
                WRITING_SKILL_SLUG: _writing_plan(),
                SPEAKING_SKILL_SLUG: _speaking_plan(),
            }.get(slug),
        ),
        patch(
            "app.payments.service.repository.get_user_exam_module",
            return_value=None,
        ),
        patch(
            "app.payments.service.repository.ensure_user_program_usage",
            side_effect=_ensure,
        ),
        patch(
            "app.payments.service.get_subscription",
            return_value=SubscriptionOut(
                is_active=True,
                plan_slug=DUAL_BUNDLE_SLUG,
                plan_name="Dual Bundle",
            ),
        ),
        patch("app.payments.service.repository.invalidate_active_subscription_cache"),
        patch(
            "app.payments.service.repository.confirm_payment_paid_bundle"
        ) as bundle,
    ):
        service.confirm_payment_paid(
            razorpay_order_id=ORDER_ID,
            razorpay_payment_id=PAY_ID,
            captured_amount=179900,
        )

    bundle.assert_not_called()
    assert len(usage_store) == 2
    assert usage_store[PROGRAM_SKILL_WRITING]["mocks_granted"] == 1
    assert usage_store[PROGRAM_SKILL_SPEAKING]["mocks_granted"] == 1
    assert usage_store[PROGRAM_SKILL_WRITING]["mocks_used"] == 0
    assert usage_store[PROGRAM_SKILL_SPEAKING]["mocks_used"] == 0
    # Heal still calls ensure, but ensure returns existing rows without mutation.
    assert all(c["mocks_granted"] == 1 for c in ensure_calls)
