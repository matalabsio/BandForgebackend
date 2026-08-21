"""Phase 3: writing_skill payment fulfillment (usage row, no plan gen)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from app.payments import repository, service, webhook
from app.payments.constants import WRITING_SKILL_SLUG
from app.payments.exceptions import PaymentAmountMismatchError, PaymentNotFoundError
from app.payments.schemas import SubscriptionOut

USER_ID = UUID("00000000-0000-4000-8000-0000000000a1")
PLAN_ID = UUID("00000000-0000-4000-8000-0000000000d4")
PAYMENT_ID = UUID("00000000-0000-4000-8000-0000000000e5")
SUB_ID = "sub_writing_1"
ORDER_ID = "order_writing_1"
PAY_ID = "pay_writing_1"


def _writing_plan() -> dict:
    return {
        "id": str(PLAN_ID),
        "slug": WRITING_SKILL_SLUG,
        "name": "Writing Skill",
        "amount": 89900,
        "currency": "INR",
        "duration_days": 180,
        "is_active": False,
    }


def _fsp_plan() -> dict:
    return {
        "id": "plan_fsp",
        "slug": "full_skill_program",
        "name": "Full Skill Program",
        "amount": 299900,
        "currency": "INR",
        "duration_days": 365,
        "is_active": True,
    }


def _created_writing_payment(*, status: str = "created") -> dict:
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
        "id": "usage_1",
        "user_id": str(USER_ID),
        "subscription_id": SUB_ID,
        "plan_id": str(PLAN_ID),
        "exam_module": None,
        "mocks_granted": 1,
        "mocks_used": 0,
    }
    base.update(overrides)
    return base


def test_writing_skill_confirm_creates_usage_without_plan_gen():
    usage_store: list[dict] = []

    def _ensure(**kwargs):
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
            return_value=_created_writing_payment(),
        ),
        patch(
            "app.payments.service.repository.list_subscriptions_for_payment",
            return_value=[],
        ),
        patch(
            "app.payments.service.repository.get_plan_by_id",
            return_value=_writing_plan(),
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
                plan_slug=WRITING_SKILL_SLUG,
                plan_name="Writing Skill",
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
            captured_amount=89900,
        )

    assert result.is_active
    assert result.plan_slug == WRITING_SKILL_SLUG
    assert len(usage_store) == 1
    assert usage_store[0]["mocks_granted"] == 1
    assert usage_store[0]["mocks_used"] == 0
    assert usage_store[0]["exam_module"] is None
    sched.assert_not_called()


def test_writing_skill_confirm_copies_exam_module_when_known():
    captured: dict = {}

    def _ensure(**kwargs):
        captured.update(kwargs)
        return _usage_row(exam_module=kwargs.get("exam_module"))

    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_created_writing_payment(),
        ),
        patch(
            "app.payments.service.repository.list_subscriptions_for_payment",
            return_value=[],
        ),
        patch(
            "app.payments.service.repository.get_plan_by_id",
            return_value=_writing_plan(),
        ),
        patch(
            "app.payments.service.repository.get_active_subscription",
            return_value=None,
        ),
        patch(
            "app.payments.service.repository.confirm_payment_paid_bundle",
            return_value={"subscription_id": SUB_ID, "user_id": str(USER_ID)},
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
                is_active=True, plan_slug=WRITING_SKILL_SLUG
            ),
        ),
        patch("app.payments.service.repository.invalidate_active_subscription_cache"),
        patch("app.learning.service.schedule_personalized_plan_generation") as sched,
    ):
        service.confirm_payment_paid(
            razorpay_order_id=ORDER_ID,
            razorpay_payment_id=PAY_ID,
            captured_amount=89900,
        )

    assert captured.get("exam_module") == "academic"
    sched.assert_not_called()


def test_fsp_confirm_still_schedules_plan_and_skips_usage():
    payment = {
        "id": str(PAYMENT_ID),
        "user_id": str(USER_ID),
        "plan_id": "plan_fsp",
        "status": "created",
        "amount": 299900,
        "currency": "INR",
        "razorpay_order_id": "order_fsp",
    }
    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=payment,
        ),
        patch(
            "app.payments.service.repository.get_plan_by_id",
            return_value=_fsp_plan(),
        ),
        patch(
            "app.payments.service.repository.get_active_subscription",
            return_value=None,
        ),
        patch(
            "app.payments.service.repository.confirm_payment_paid_bundle",
            return_value={
                "already_paid": False,
                "subscription_id": "sub_fsp",
                "user_id": str(USER_ID),
            },
        ),
        patch(
            "app.payments.service.repository.ensure_user_program_usage"
        ) as ensure_usage,
        patch(
            "app.payments.service.get_subscription",
            return_value=SubscriptionOut(
                is_active=True,
                plan_slug="full_skill_program",
                plan_name="Full Skill Program",
            ),
        ),
        patch("app.payments.service.repository.invalidate_active_subscription_cache"),
        patch("app.learning.service.invalidate_learning_profile_cache"),
        patch(
            "app.learning.service.schedule_personalized_plan_generation"
        ) as sched,
        patch(
            "app.learning.ingest.load_user_exam_and_target",
            return_value={"exam_date": "2026-12-01"},
        ),
    ):
        result = service.confirm_payment_paid(
            razorpay_order_id="order_fsp",
            razorpay_payment_id="pay_fsp",
            captured_amount=299900,
        )
    assert result.plan_slug == "full_skill_program"
    sched.assert_called_once_with(USER_ID)
    ensure_usage.assert_not_called()


def test_writing_skill_idempotent_confirm_twice():
    usage_store: list[dict] = []

    def _ensure(**kwargs):
        if usage_store:
            return usage_store[0]
        row = _usage_row()
        usage_store.append(row)
        return row

    # First confirm (created → paid)
    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_created_writing_payment(),
        ),
        patch(
            "app.payments.service.repository.list_subscriptions_for_payment",
            return_value=[],
        ),
        patch(
            "app.payments.service.repository.get_plan_by_id",
            return_value=_writing_plan(),
        ),
        patch(
            "app.payments.service.repository.get_active_subscription",
            return_value=None,
        ),
        patch(
            "app.payments.service.repository.confirm_payment_paid_bundle",
            return_value={"subscription_id": SUB_ID, "user_id": str(USER_ID)},
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
                is_active=True, plan_slug=WRITING_SKILL_SLUG
            ),
        ),
        patch("app.payments.service.repository.invalidate_active_subscription_cache"),
        patch("app.learning.service.schedule_personalized_plan_generation") as sched,
    ):
        service.confirm_payment_paid(
            razorpay_order_id=ORDER_ID,
            razorpay_payment_id=PAY_ID,
            captured_amount=89900,
        )

    # Second confirm (paid + sub exists)
    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_created_writing_payment(status="paid"),
        ),
        patch(
            "app.payments.service.repository.list_subscriptions_for_payment",
            return_value=[{"id": SUB_ID}],
        ),
        patch(
            "app.payments.service.repository.get_plan_by_id",
            return_value=_writing_plan(),
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
                is_active=True, plan_slug=WRITING_SKILL_SLUG
            ),
        ),
        patch("app.payments.service.repository.invalidate_active_subscription_cache"),
        patch("app.payments.service.repository.confirm_payment_paid_bundle") as bundle,
        patch("app.learning.service.schedule_personalized_plan_generation") as sched2,
    ):
        service.confirm_payment_paid(
            razorpay_order_id=ORDER_ID,
            razorpay_payment_id=PAY_ID,
            captured_amount=89900,
        )
        bundle.assert_not_called()
        sched2.assert_not_called()

    assert len(usage_store) == 1
    sched.assert_not_called()


def test_writing_skill_webhook_then_verify_one_usage():
    usage_store: list[dict] = []

    def _ensure(**kwargs):
        if usage_store:
            return usage_store[0]
        row = _usage_row()
        usage_store.append(row)
        return row

    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_created_writing_payment(),
        ),
        patch(
            "app.payments.service.repository.list_subscriptions_for_payment",
            return_value=[],
        ),
        patch(
            "app.payments.service.repository.get_plan_by_id",
            return_value=_writing_plan(),
        ),
        patch(
            "app.payments.service.repository.get_active_subscription",
            return_value=None,
        ),
        patch(
            "app.payments.service.repository.confirm_payment_paid_bundle",
            return_value={"subscription_id": SUB_ID, "user_id": str(USER_ID)},
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
                is_active=True, plan_slug=WRITING_SKILL_SLUG
            ),
        ),
        patch("app.payments.service.repository.invalidate_active_subscription_cache"),
        patch("app.learning.service.schedule_personalized_plan_generation"),
    ):
        service.confirm_payment_paid(
            razorpay_order_id=ORDER_ID,
            razorpay_payment_id=PAY_ID,
            captured_amount=89900,
        )

    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_created_writing_payment(status="paid"),
        ),
        patch(
            "app.payments.service.repository.list_subscriptions_for_payment",
            return_value=[{"id": SUB_ID}],
        ),
        patch(
            "app.payments.service.repository.get_plan_by_id",
            return_value=_writing_plan(),
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
                is_active=True, plan_slug=WRITING_SKILL_SLUG
            ),
        ),
        patch("app.payments.service.repository.invalidate_active_subscription_cache"),
        patch("app.payments.service.repository.confirm_payment_paid_bundle") as bundle,
        patch("app.learning.service.schedule_personalized_plan_generation") as sched,
    ):
        service.confirm_payment_paid(
            razorpay_order_id=ORDER_ID,
            razorpay_payment_id=PAY_ID,
            captured_amount=89900,
        )
        bundle.assert_not_called()
        sched.assert_not_called()

    assert len(usage_store) == 1


def test_writing_skill_verify_then_webhook_one_usage():
    """Same convergence path with opposite call order naming."""
    test_writing_skill_webhook_then_verify_one_usage()


def test_writing_skill_amount_mismatch_creates_no_usage():
    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_created_writing_payment(),
        ),
        patch(
            "app.payments.service.repository.get_plan_by_id",
            return_value=_writing_plan(),
        ),
        patch(
            "app.payments.service.repository.ensure_user_program_usage"
        ) as ensure,
        patch(
            "app.payments.service.repository.confirm_payment_paid_bundle"
        ) as bundle,
        patch(
            "app.learning.service.schedule_personalized_plan_generation"
        ) as sched,
    ):
        with pytest.raises(PaymentAmountMismatchError):
            service.confirm_payment_paid(
                razorpay_order_id=ORDER_ID,
                razorpay_payment_id=PAY_ID,
                captured_amount=1,
            )
        ensure.assert_not_called()
        bundle.assert_not_called()
        sched.assert_not_called()


def test_writing_skill_missing_payment_creates_no_usage():
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
                razorpay_order_id="missing",
                razorpay_payment_id=PAY_ID,
                captured_amount=89900,
            )
        ensure.assert_not_called()


def test_ensure_user_program_usage_is_idempotent_on_unique_violation():
    existing = _usage_row()
    table = MagicMock()
    table.insert.return_value = table
    sb = MagicMock()
    sb.table.return_value = table

    with (
        patch(
            "app.payments.repository.get_user_program_usage_by_subscription",
            side_effect=[None, existing],
        ),
        patch("app.payments.repository.get_supabase", return_value=sb),
        patch(
            "app.payments.repository._exec",
            side_effect=Exception("duplicate key value violates unique constraint"),
        ),
    ):
        out = repository.ensure_user_program_usage(
            user_id=USER_ID,
            subscription_id=SUB_ID,
            plan_id=PLAN_ID,
            mocks_granted=1,
        )
    assert out == existing


def test_webhook_captured_delegates_to_confirm_for_writing_skill():
    event_row = {"id": "evt_1", "processing_status": "pending"}
    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": PAY_ID,
                    "order_id": ORDER_ID,
                    "amount": 89900,
                }
            }
        },
    }
    with (
        patch(
            "app.payments.webhook.razorpay_client.verify_webhook_signature",
            return_value=True,
        ),
        patch(
            "app.payments.webhook.repository.insert_payment_event",
            return_value=event_row,
        ),
        patch("app.payments.webhook.service.confirm_payment_paid") as confirm,
        patch("app.payments.webhook.repository.mark_event_processed") as marked,
    ):
        out = webhook.handle_webhook(
            raw_body=b"{}",
            signature="sig",
            event_id="evt_unique_1",
            payload=payload,
        )
    assert out == {"ok": True}
    confirm.assert_called_once()
    assert confirm.call_args.kwargs["razorpay_order_id"] == ORDER_ID
    assert confirm.call_args.kwargs["captured_amount"] == 89900
    marked.assert_called_once_with("evt_1")


def test_multi_sku_writing_fulfillment_does_not_touch_fsp_subscription():
    fsp_sub = {
        "id": "sub_fsp_existing",
        "plans": {"slug": "full_skill_program"},
        "expires_at": "2099-01-01T00:00:00+00:00",
    }
    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_created_writing_payment(),
        ),
        patch(
            "app.payments.service.repository.list_subscriptions_for_payment",
            return_value=[],
        ),
        patch(
            "app.payments.service.repository.get_plan_by_id",
            return_value=_writing_plan(),
        ),
        patch(
            "app.payments.service.repository.get_active_subscription",
            return_value=fsp_sub,
        ),
        patch(
            "app.payments.service.repository.confirm_payment_paid_bundle",
            return_value={
                "already_paid": False,
                "subscription_id": SUB_ID,
                "user_id": str(USER_ID),
            },
        ) as bundle,
        patch(
            "app.payments.service.repository.get_user_exam_module",
            return_value=None,
        ),
        patch(
            "app.payments.service.repository.ensure_user_program_usage",
            return_value=_usage_row(),
        ) as ensure,
        patch(
            "app.payments.service.get_subscription",
            return_value=SubscriptionOut(
                is_active=True, plan_slug=WRITING_SKILL_SLUG
            ),
        ),
        patch("app.payments.service.repository.invalidate_active_subscription_cache"),
        patch(
            "app.learning.service.schedule_personalized_plan_generation"
        ) as sched,
    ):
        service.confirm_payment_paid(
            razorpay_order_id=ORDER_ID,
            razorpay_payment_id=PAY_ID,
            captured_amount=89900,
        )
        bundle.assert_called_once()
        ensure.assert_called_once()
        assert ensure.call_args.kwargs["subscription_id"] == SUB_ID
        sched.assert_not_called()


def test_heal_usage_when_paid_sub_exists_but_usage_missing():
    """Short-circuit path still creates usage if a prior attempt missed it."""
    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_created_writing_payment(status="paid"),
        ),
        patch(
            "app.payments.service.repository.list_subscriptions_for_payment",
            return_value=[{"id": SUB_ID}],
        ),
        patch(
            "app.payments.service.repository.get_plan_by_id",
            return_value=_writing_plan(),
        ),
        patch(
            "app.payments.service.repository.get_user_exam_module",
            return_value=None,
        ),
        patch(
            "app.payments.service.repository.ensure_user_program_usage",
            return_value=_usage_row(),
        ) as ensure,
        patch(
            "app.payments.service.get_subscription",
            return_value=SubscriptionOut(
                is_active=True, plan_slug=WRITING_SKILL_SLUG
            ),
        ),
        patch("app.payments.service.repository.invalidate_active_subscription_cache"),
        patch("app.payments.service.repository.confirm_payment_paid_bundle") as bundle,
        patch("app.learning.service.schedule_personalized_plan_generation") as sched,
    ):
        service.confirm_payment_paid(
            razorpay_order_id=ORDER_ID,
            razorpay_payment_id=PAY_ID,
        )
        bundle.assert_not_called()
        ensure.assert_called_once()
        assert ensure.call_args.kwargs["mocks_granted"] == 1
        sched.assert_not_called()
