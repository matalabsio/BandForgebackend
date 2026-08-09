"""Payments module tests: data minimization, signatures, idempotency, stacking."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.auth.schemas import UserPublic
from app.payments import razorpay_client, repository, service, webhook
from app.payments.constants import EVENT_PROCESSED
from app.payments.exceptions import PaymentConsistencyError
from app.payments.schemas import (
    RazorpayOrderPayload,
    SubscriptionOut,
    VerifyPaymentRequest,
)

USER_ID = UUID("00000000-0000-4000-8000-0000000000a1")
PLAN_ID = UUID("00000000-0000-4000-8000-0000000000b2")
PAYMENT_ID = UUID("00000000-0000-4000-8000-0000000000c3")
SECRET = "rzp_secret_test"


def _user() -> UserPublic:
    return UserPublic(
        id=USER_ID,
        email="student@example.com",
        full_name="Test Student",
        phone="9876543210",
        target_band=7.5,
    )


def _plan() -> dict:
    return {
        "id": str(PLAN_ID),
        "slug": "premium_monthly",
        "name": "Premium",
        "amount": 99900,
        "currency": "INR",
        "duration_days": 30,
    }


def _fake_settings(**overrides) -> SimpleNamespace:
    base = {
        "razorpay_enabled": True,
        "razorpay_key_id": "rzp_test_key",
        "razorpay_key_secret": SECRET,
        "razorpay_webhook_secret": SECRET,
        "razorpay_checkout_config_id": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _created_payment(*, order_id: str = "order_test_2") -> dict:
    return {
        "id": str(PAYMENT_ID),
        "user_id": str(USER_ID),
        "plan_id": str(PLAN_ID),
        "status": "created",
        "amount": 99900,
        "currency": "INR",
        "razorpay_order_id": order_id,
    }


@contextmanager
def _create_order_persistence(order_id: str, *, row: dict | None = None):
    """Stub insert + consistency re-read (count==1 + matching row)."""
    verified = row if row is not None else _created_payment(order_id=order_id)
    with (
        patch(
            "app.payments.service.repository.insert_payment",
            return_value={"id": str(verified.get("id") or PAYMENT_ID)},
        ),
        patch(
            "app.payments.service.repository.count_payments_by_order_id",
            return_value=1,
        ),
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=verified,
        ),
    ):
        yield


# --- data minimization -----------------------------------------------------


def test_create_order_payload_has_no_notes_or_metadata():
    captured = {}

    def fake_create(payload):
        captured["payload"] = payload
        return {"id": "order_test_1"}

    fake_client = SimpleNamespace(order=SimpleNamespace(create=fake_create))
    with (
        patch("app.payments.razorpay_client._client", return_value=fake_client),
        patch("app.payments.razorpay_client.get_settings", return_value=_fake_settings()),
    ):
        payload = RazorpayOrderPayload(amount=99900, currency="INR", receipt="abcd1234")
        razorpay_client.create_order(payload)

    sent = captured["payload"]
    assert set(sent.keys()) <= {
        "amount",
        "currency",
        "receipt",
        "payment_capture",
        "checkout_config_id",
    }
    assert "notes" not in sent
    assert "user_id" not in sent
    assert "plan_slug" not in sent
    assert sent["amount"] == 99900
    assert "checkout_config_id" not in sent


def test_create_order_forwards_checkout_config_id_when_configured():
    captured = {}

    def fake_create(payload):
        captured["payload"] = payload
        return {"id": "order_test_config"}

    fake_client = SimpleNamespace(order=SimpleNamespace(create=fake_create))
    with (
        patch("app.payments.razorpay_client._client", return_value=fake_client),
        patch(
            "app.payments.razorpay_client.get_settings",
            return_value=_fake_settings(razorpay_checkout_config_id="config_test_abc"),
        ),
    ):
        payload = RazorpayOrderPayload(amount=99900, currency="INR", receipt="abcd1234")
        razorpay_client.create_order(payload)

    assert captured["payload"]["checkout_config_id"] == "config_test_abc"


def test_create_order_response_includes_checkout_config_id_when_configured():
    with (
        patch(
            "app.payments.service.get_settings",
            return_value=_fake_settings(razorpay_checkout_config_id="config_resp_xyz"),
        ),
        patch("app.payments.service.repository.get_plan_by_slug", return_value=_plan()),
        patch(
            "app.payments.razorpay_client.create_order",
            return_value={"id": "order_with_config"},
        ),
        patch("app.payments.service.secrets.token_hex", return_value="a" * 32),
        _create_order_persistence("order_with_config"),
    ):
        resp = service.create_order(user=_user(), plan_slug="premium_monthly")

    assert resp.checkout_config_id == "config_resp_xyz"


def test_create_order_uses_db_amount_minimal_contact_and_long_receipt():
    captured = {}

    def fake_rzp_create(payload: RazorpayOrderPayload):
        captured["payload"] = payload
        return {"id": "order_test_2"}

    with (
        patch("app.payments.service.get_settings", return_value=_fake_settings()),
        patch("app.payments.service.repository.get_plan_by_slug", return_value=_plan()),
        patch("app.payments.razorpay_client.create_order", side_effect=fake_rzp_create),
        patch("app.payments.service.secrets.token_hex", return_value="a" * 32),
        _create_order_persistence("order_test_2"),
    ):
        resp = service.create_order(user=_user(), plan_slug="premium_monthly")

    assert captured["payload"].amount == 99900
    assert len(captured["payload"].receipt) == 32
    assert resp.amount == 99900
    assert set(resp.checkout_contact.model_dump().keys()) == {"name", "email", "contact"}
    assert resp.checkout_contact.name == "Test Student"
    assert resp.checkout_contact.contact == "+919876543210"
    assert resp.key_id == "rzp_test_key"


def test_checkout_contact_omits_invalid_phone():
    user = _user()
    user = user.model_copy(update={"phone": "+91 invalid"})
    with (
        patch("app.payments.service.get_settings", return_value=_fake_settings()),
        patch("app.payments.service.repository.get_plan_by_slug", return_value=_plan()),
        patch("app.payments.razorpay_client.create_order", return_value={"id": "order_x"}),
        patch("app.payments.service.secrets.token_hex", return_value="a" * 32),
        _create_order_persistence("order_x"),
    ):
        resp = service.create_order(user=user, plan_slug="premium_monthly")
    assert resp.checkout_contact.contact is None


def test_create_order_rejects_unknown_plan():
    with (
        patch("app.payments.service.get_settings", return_value=_fake_settings()),
        patch("app.payments.service.repository.get_plan_by_slug", return_value=None),
    ):
        with pytest.raises(HTTPException) as exc:
            service.create_order(user=_user(), plan_slug="nope")
        assert exc.value.status_code == 404


# --- create-order DB consistency gate (Phase 4) -----------------------------


def test_create_order_consistency_ok_on_first_reread():
    with (
        patch("app.payments.service.get_settings", return_value=_fake_settings()),
        patch("app.payments.service.repository.get_plan_by_slug", return_value=_plan()),
        patch(
            "app.payments.razorpay_client.create_order",
            return_value={"id": "order_ok_1"},
        ),
        patch("app.payments.service.secrets.token_hex", return_value="a" * 32),
        patch("app.payments.service.time.sleep") as sleep_mock,
        _create_order_persistence("order_ok_1"),
    ):
        resp = service.create_order(user=_user(), plan_slug="premium_monthly")

    assert resp.order_id == "order_ok_1"
    sleep_mock.assert_not_called()


def test_create_order_consistency_retries_once_then_succeeds():
    verified = _created_payment(order_id="order_retry")
    with (
        patch("app.payments.service.get_settings", return_value=_fake_settings()),
        patch("app.payments.service.repository.get_plan_by_slug", return_value=_plan()),
        patch(
            "app.payments.razorpay_client.create_order",
            return_value={"id": "order_retry"},
        ),
        patch(
            "app.payments.service.repository.insert_payment",
            return_value={"id": str(PAYMENT_ID)},
        ),
        patch(
            "app.payments.service.repository.count_payments_by_order_id",
            side_effect=[0, 1],
        ),
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=verified,
        ),
        patch("app.payments.service.secrets.token_hex", return_value="a" * 32),
        patch("app.payments.service.time.sleep") as sleep_mock,
    ):
        resp = service.create_order(user=_user(), plan_slug="premium_monthly")

    assert resp.order_id == "order_retry"
    sleep_mock.assert_called_once_with(0.15)


def test_create_order_consistency_missing_both_attempts_raises():
    with (
        patch("app.payments.service.get_settings", return_value=_fake_settings()),
        patch("app.payments.service.repository.get_plan_by_slug", return_value=_plan()),
        patch(
            "app.payments.razorpay_client.create_order",
            return_value={"id": "order_miss"},
        ),
        patch(
            "app.payments.service.repository.insert_payment",
            return_value={"id": str(PAYMENT_ID)},
        ),
        patch(
            "app.payments.service.repository.count_payments_by_order_id",
            return_value=0,
        ),
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=None,
        ),
        patch("app.payments.service.secrets.token_hex", return_value="a" * 32),
        patch("app.payments.service.time.sleep") as sleep_mock,
    ):
        with pytest.raises(PaymentConsistencyError) as exc:
            service.create_order(user=_user(), plan_slug="premium_monthly")
        assert exc.value.status_code == 503

    sleep_mock.assert_called_once_with(0.15)


def test_create_order_consistency_wrong_status_fails():
    bad = {**_created_payment(order_id="order_bad_status"), "status": "paid"}
    with (
        patch("app.payments.service.get_settings", return_value=_fake_settings()),
        patch("app.payments.service.repository.get_plan_by_slug", return_value=_plan()),
        patch(
            "app.payments.razorpay_client.create_order",
            return_value={"id": "order_bad_status"},
        ),
        patch("app.payments.service.secrets.token_hex", return_value="a" * 32),
        patch("app.payments.service.time.sleep"),
        _create_order_persistence("order_bad_status", row=bad),
    ):
        with pytest.raises(PaymentConsistencyError):
            service.create_order(user=_user(), plan_slug="premium_monthly")


def test_create_order_consistency_wrong_amount_fails():
    bad = {**_created_payment(order_id="order_bad_amt"), "amount": 1}
    with (
        patch("app.payments.service.get_settings", return_value=_fake_settings()),
        patch("app.payments.service.repository.get_plan_by_slug", return_value=_plan()),
        patch(
            "app.payments.razorpay_client.create_order",
            return_value={"id": "order_bad_amt"},
        ),
        patch("app.payments.service.secrets.token_hex", return_value="a" * 32),
        patch("app.payments.service.time.sleep"),
        _create_order_persistence("order_bad_amt", row=bad),
    ):
        with pytest.raises(PaymentConsistencyError):
            service.create_order(user=_user(), plan_slug="premium_monthly")


def test_create_order_consistency_wrong_user_fails():
    bad = {
        **_created_payment(order_id="order_bad_user"),
        "user_id": str(UUID(int=99)),
    }
    with (
        patch("app.payments.service.get_settings", return_value=_fake_settings()),
        patch("app.payments.service.repository.get_plan_by_slug", return_value=_plan()),
        patch(
            "app.payments.razorpay_client.create_order",
            return_value={"id": "order_bad_user"},
        ),
        patch("app.payments.service.secrets.token_hex", return_value="a" * 32),
        patch("app.payments.service.time.sleep"),
        _create_order_persistence("order_bad_user", row=bad),
    ):
        with pytest.raises(PaymentConsistencyError):
            service.create_order(user=_user(), plan_slug="premium_monthly")


def test_create_order_consistency_duplicate_order_id_fails_immediately():
    with (
        patch("app.payments.service.get_settings", return_value=_fake_settings()),
        patch("app.payments.service.repository.get_plan_by_slug", return_value=_plan()),
        patch(
            "app.payments.razorpay_client.create_order",
            return_value={"id": "order_dup"},
        ),
        patch(
            "app.payments.service.repository.insert_payment",
            return_value={"id": str(PAYMENT_ID)},
        ),
        patch(
            "app.payments.service.repository.count_payments_by_order_id",
            return_value=2,
        ),
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_created_payment(order_id="order_dup"),
        ),
        patch("app.payments.service.secrets.token_hex", return_value="a" * 32),
        patch("app.payments.service.time.sleep") as sleep_mock,
    ):
        with pytest.raises(PaymentConsistencyError):
            service.create_order(user=_user(), plan_slug="premium_monthly")

    sleep_mock.assert_not_called()


def test_razorpay_client_maps_auth_failure_to_503():
    from unittest.mock import MagicMock

    from razorpay.errors import BadRequestError

    from app.payments.schemas import RazorpayOrderPayload

    fake_client = MagicMock()
    fake_client.order.create.side_effect = BadRequestError("Authentication failed")
    with patch("app.payments.razorpay_client._client", return_value=fake_client):
        with pytest.raises(HTTPException) as exc:
            razorpay_client.create_order(
                RazorpayOrderPayload(amount=100, currency="INR", receipt="r1")
            )
        assert exc.value.status_code == 503
        assert "authentication failed" in str(exc.value.detail).lower()


# --- signatures ------------------------------------------------------------


def _sign(message: str) -> str:
    return hmac.new(SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()


def test_verify_payment_signature_valid_and_invalid():
    with patch("app.payments.razorpay_client.get_settings", return_value=_fake_settings()):
        good = _sign("order_1|pay_1")
        assert razorpay_client.verify_payment_signature(
            razorpay_order_id="order_1",
            razorpay_payment_id="pay_1",
            razorpay_signature=good,
        )
        assert not razorpay_client.verify_payment_signature(
            razorpay_order_id="order_1",
            razorpay_payment_id="pay_1",
            razorpay_signature="deadbeef",
        )


def test_verify_webhook_signature_valid_and_invalid():
    with patch("app.payments.razorpay_client.get_settings", return_value=_fake_settings()):
        body = b'{"event":"payment.captured"}'
        sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        assert razorpay_client.verify_webhook_signature(raw_body=body, signature=sig)
        assert not razorpay_client.verify_webhook_signature(raw_body=body, signature="x")


# --- confirm_payment_paid (unified path) -----------------------------------


def test_confirm_payment_paid_idempotent_for_already_paid():
    paid_payment = {**_created_payment(), "status": "paid"}
    active_sub = SubscriptionOut(is_active=True, plan_name="Premium")
    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=paid_payment,
        ),
        patch(
            "app.payments.service.repository.list_subscriptions_for_payment",
            return_value=[{"id": "sub_1"}],
        ),
        patch("app.payments.service.get_subscription", return_value=active_sub),
        patch("app.payments.service.repository.confirm_payment_paid_bundle") as bundle,
        patch(
            "app.payments.service.repository.invalidate_active_subscription_cache"
        ) as inv_sub,
    ):
        result = service.confirm_payment_paid(
            razorpay_order_id="order_x",
            razorpay_payment_id="pay_x",
        )
        assert result.is_active
        bundle.assert_not_called()
        inv_sub.assert_called_once_with(USER_ID)


def test_confirm_payment_paid_heals_paid_without_subscription():
    paid_payment = {**_created_payment(), "status": "paid"}
    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=paid_payment,
        ),
        patch(
            "app.payments.service.repository.list_subscriptions_for_payment",
            return_value=[],
        ),
        patch("app.payments.service.repository.get_plan_by_id", return_value=_plan()),
        patch(
            "app.payments.service.repository.get_active_subscription",
            return_value=None,
        ),
        patch(
            "app.payments.service.repository.confirm_payment_paid_bundle",
            return_value={"already_paid": True, "subscription_id": "sub_new"},
        ) as bundle,
        patch(
            "app.payments.service.get_subscription",
            return_value=SubscriptionOut(is_active=True, plan_name="Premium"),
        ),
        patch(
            "app.payments.service.repository.invalidate_active_subscription_cache"
        ) as inv_sub,
    ):
        result = service.confirm_payment_paid(
            razorpay_order_id="order_x",
            razorpay_payment_id="pay_x",
            captured_amount=99900,
        )
        assert result.is_active
        bundle.assert_called_once()
        inv_sub.assert_called_with(USER_ID)


def test_confirm_payment_paid_calls_bundle_for_new_payment():
    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_created_payment(),
        ),
        patch("app.payments.service.repository.get_plan_by_id", return_value=_plan()),
        patch(
            "app.payments.service.repository.get_active_subscription",
            return_value=None,
        ),
        patch(
            "app.payments.service.repository.confirm_payment_paid_bundle",
            return_value={"already_paid": False},
        ) as bundle,
        patch(
            "app.payments.service.get_subscription",
            return_value=SubscriptionOut(is_active=True, plan_name="Premium"),
        ),
        patch(
            "app.payments.service.repository.invalidate_active_subscription_cache"
        ) as inv_sub,
    ):
        service.confirm_payment_paid(
            razorpay_order_id="order_x",
            razorpay_payment_id="pay_x",
            razorpay_signature="sig",
            captured_amount=99900,
        )
        bundle.assert_called_once()
        inv_sub.assert_called_with(USER_ID)
        kwargs = bundle.call_args.kwargs
        assert kwargs["razorpay_order_id"] == "order_x"
        assert kwargs["razorpay_payment_id"] == "pay_x"


def test_confirm_payment_paid_invalidates_learning_cache_for_full_skill():
    fsp_plan = {**_plan(), "slug": "full_skill_program", "name": "Full Skill Program"}
    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_created_payment(),
        ),
        patch("app.payments.service.repository.get_plan_by_id", return_value=fsp_plan),
        patch(
            "app.payments.service.repository.get_active_subscription",
            return_value=None,
        ),
        patch(
            "app.payments.service.repository.confirm_payment_paid_bundle",
            return_value={"already_paid": False, "user_id": str(USER_ID)},
        ),
        patch(
            "app.payments.service.get_subscription",
            return_value=SubscriptionOut(
                is_active=True,
                plan_slug="full_skill_program",
                plan_name="Full Skill Program",
            ),
        ),
        patch("app.payments.service.repository.invalidate_active_subscription_cache"),
        patch(
            "app.learning.service.invalidate_learning_profile_cache"
        ) as inv_learn,
        patch(
            "app.learning.service.schedule_personalized_plan_generation"
        ) as sched,
        patch(
            "app.learning.ingest.load_user_exam_and_target",
            return_value={"exam_date": "2026-12-01"},
        ),
    ):
        result = service.confirm_payment_paid(
            razorpay_order_id="order_x",
            razorpay_payment_id="pay_x",
            razorpay_signature="sig",
            captured_amount=99900,
        )
        assert result.is_active
        inv_learn.assert_called_once_with(USER_ID)
        sched.assert_called_once_with(USER_ID)


def test_get_active_subscription_use_cache_false_skips_cache_write():
    empty = SimpleNamespace(data=[])
    table = MagicMock()
    table.select.return_value = table
    table.eq.return_value = table
    table.gt.return_value = table
    table.order.return_value = table
    table.limit.return_value = table
    table.execute.return_value = empty
    sb = MagicMock()
    sb.table.return_value = table
    with (
        patch("app.payments.repository.get_supabase", return_value=sb),
        patch("app.cache.hybrid_cache.get_json") as get_json,
        patch("app.cache.hybrid_cache.set_json") as set_json,
    ):
        assert repository.get_active_subscription(USER_ID, use_cache=False) is None
        get_json.assert_not_called()
        set_json.assert_not_called()


def test_confirm_payment_paid_enforces_ownership():
    other_user_payment = {**_created_payment(), "user_id": str(UUID(int=99))}
    with patch(
        "app.payments.service.repository.get_payment_by_order_id",
        return_value=other_user_payment,
    ):
        with pytest.raises(HTTPException) as exc:
            service.confirm_payment_paid(
                razorpay_order_id="order_x",
                razorpay_payment_id="pay_x",
                user_id=USER_ID,
            )
        assert exc.value.status_code == 404


def test_confirm_payment_paid_raises_when_row_missing():
    with patch(
        "app.payments.service.repository.get_payment_by_order_id",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc:
            service.confirm_payment_paid(
                razorpay_order_id="order_missing",
                razorpay_payment_id="pay_x",
                user_id=USER_ID,
            )
        assert exc.value.status_code == 404
        assert "not found" in str(exc.value.detail).lower()


def test_compute_subscription_dates_stacks_on_active():
    future = datetime.now(UTC) + timedelta(days=10)
    with patch(
        "app.payments.service.repository.get_active_subscription",
        return_value={"expires_at": future.isoformat()},
    ):
        starts, expires = service._compute_subscription_dates(USER_ID, _plan())
    assert starts == future
    assert expires == future + timedelta(days=30)


# --- verify flow -----------------------------------------------------------


def test_verify_rejects_bad_signature():
    with (
        patch("app.payments.service.get_settings", return_value=_fake_settings()),
        patch(
            "app.payments.razorpay_client.verify_payment_signature",
            return_value=False,
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            service.verify_payment(
                user=_user(),
                body=VerifyPaymentRequest(
                    razorpay_order_id="o",
                    razorpay_payment_id="p",
                    razorpay_signature="bad",
                ),
            )
        assert exc.value.status_code == 400


def test_verify_delegates_to_confirm_payment_paid():
    with (
        patch("app.payments.service.get_settings", return_value=_fake_settings()),
        patch(
            "app.payments.razorpay_client.verify_payment_signature",
            return_value=True,
        ),
        patch(
            "app.payments.razorpay_client.fetch_payment",
            return_value={"status": "captured", "captured": True, "amount": 99900},
        ),
        patch("app.payments.service.confirm_payment_paid") as confirm,
    ):
        confirm.return_value = SubscriptionOut(is_active=True, plan_name="Premium")
        resp = service.verify_payment(
            user=_user(),
            body=VerifyPaymentRequest(
                razorpay_order_id="o",
                razorpay_payment_id="p",
                razorpay_signature="good",
            ),
        )
        assert resp.subscription.is_active
        confirm.assert_called_once()


def test_verify_rejects_authorized_only_payment():
    from app.payments.exceptions import PaymentNotCapturedError

    with (
        patch("app.payments.service.get_settings", return_value=_fake_settings()),
        patch(
            "app.payments.razorpay_client.verify_payment_signature",
            return_value=True,
        ),
        patch(
            "app.payments.razorpay_client.fetch_payment",
            return_value={"status": "authorized", "captured": False, "amount": 99900},
        ),
        patch("app.payments.service.confirm_payment_paid") as confirm,
    ):
        with pytest.raises(PaymentNotCapturedError):
            service.verify_payment(
                user=_user(),
                body=VerifyPaymentRequest(
                    razorpay_order_id="o",
                    razorpay_payment_id="p",
                    razorpay_signature="good",
                ),
            )
        confirm.assert_not_called()


# --- webhook ---------------------------------------------------------------


def test_webhook_rejects_bad_signature():
    with patch(
        "app.payments.razorpay_client.verify_webhook_signature", return_value=False
    ):
        with pytest.raises(HTTPException) as exc:
            webhook.handle_webhook(
                raw_body=b"{}", signature="bad", event_id="evt_1", payload={}
            )
        assert exc.value.status_code == 400


def test_webhook_is_idempotent_on_duplicate_event():
    with (
        patch(
            "app.payments.razorpay_client.verify_webhook_signature", return_value=True
        ),
        patch(
            "app.payments.repository.insert_payment_event", return_value=None
        ) as insert,
        patch(
            "app.payments.repository.get_payment_event_by_razorpay_event_id",
            return_value={
                "id": "evt_row",
                "processing_status": "processed",
                "retry_count": 0,
            },
        ),
    ):
        result = webhook.handle_webhook(
            raw_body=b'{"event":"payment.captured"}',
            signature="ok",
            event_id="evt_dup",
            payload={"event": "payment.captured"},
            headers={"X-Razorpay-Event-Id": "evt_dup"},
        )
        assert result == {"ok": True, "duplicate": True}
        insert.assert_called_once()
        call_kwargs = insert.call_args.kwargs
        assert call_kwargs["headers"]["X-Razorpay-Event-Id"] == "evt_dup"


def test_webhook_reprocesses_failed_event_on_retry():
    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {"id": "pay_x", "order_id": "order_x", "amount": 49900}
            }
        },
    }
    with (
        patch(
            "app.payments.razorpay_client.verify_webhook_signature", return_value=True
        ),
        patch("app.payments.repository.insert_payment_event", return_value=None),
        patch(
            "app.payments.repository.get_payment_event_by_razorpay_event_id",
            return_value={
                "id": "evt_failed",
                "processing_status": "failed",
                "retry_count": 1,
            },
        ),
        patch(
            "app.payments.repository.claim_payment_event_for_retry",
            return_value={
                "id": "evt_failed",
                "processing_status": "pending",
                "retry_count": 2,
            },
        ) as claim,
        patch("app.payments.service.confirm_payment_paid") as confirm,
        patch("app.payments.repository.mark_event_processed") as processed,
    ):
        result = webhook.handle_webhook(
            raw_body=b"{}",
            signature="ok",
            event_id="evt_retry",
            payload=payload,
        )
    assert result == {"ok": True, "reprocess": True}
    claim.assert_called_once_with("evt_failed")
    confirm.assert_called_once()
    processed.assert_called_once_with("evt_failed")


def test_webhook_rejects_missing_event_id():
    from app.payments.exceptions import WebhookEventIdRequiredError

    with patch(
        "app.payments.razorpay_client.verify_webhook_signature", return_value=True
    ):
        with pytest.raises(WebhookEventIdRequiredError) as exc:
            webhook.handle_webhook(
                raw_body=b"{}",
                signature="ok",
                event_id=None,
                payload={"event": "payment.captured"},
            )
        assert exc.value.status_code == 400


def test_webhook_payment_captured_uses_confirm_payment_paid():
    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {"id": "pay_x", "order_id": "order_x", "amount": 99900}
            }
        },
    }
    with (
        patch(
            "app.payments.razorpay_client.verify_webhook_signature", return_value=True
        ),
        patch(
            "app.payments.repository.insert_payment_event",
            return_value={"id": "evt_row_1"},
        ),
        patch("app.payments.service.confirm_payment_paid") as confirm,
        patch("app.payments.repository.mark_event_processed") as processed,
    ):
        result = webhook.handle_webhook(
            raw_body=b"{}",
            signature="ok",
            event_id="evt_new",
            payload=payload,
            headers={"X-Razorpay-Signature": "secret"},
        )
        assert result == {"ok": True}
        confirm.assert_called_once_with(
            razorpay_order_id="order_x",
            razorpay_payment_id="pay_x",
            captured_amount=99900,
        )
        processed.assert_called_once()


def test_webhook_payment_captured_fetches_amount_when_missing():
    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {"entity": {"id": "pay_x", "order_id": "order_x"}}
        },
    }
    with (
        patch(
            "app.payments.razorpay_client.verify_webhook_signature", return_value=True
        ),
        patch(
            "app.payments.repository.insert_payment_event",
            return_value={"id": "evt_row_1"},
        ),
        patch(
            "app.payments.razorpay_client.fetch_payment",
            return_value={"amount": 99900, "status": "captured"},
        ) as fetch,
        patch("app.payments.service.confirm_payment_paid") as confirm,
        patch("app.payments.repository.mark_event_processed"),
    ):
        result = webhook.handle_webhook(
            raw_body=b"{}",
            signature="ok",
            event_id="evt_fetch_amt",
            payload=payload,
            headers={"X-Razorpay-Signature": "secret"},
        )
        assert result == {"ok": True}
        fetch.assert_called_once_with("pay_x")
        confirm.assert_called_once_with(
            razorpay_order_id="order_x",
            razorpay_payment_id="pay_x",
            captured_amount=99900,
        )


def test_webhook_sanitizes_signature_header():
    captured = {}

    def capture_insert(**kwargs):
        captured.update(kwargs)
        return {"id": "evt_1"}

    with (
        patch(
            "app.payments.razorpay_client.verify_webhook_signature", return_value=True
        ),
        patch(
            "app.payments.repository.insert_payment_event",
            side_effect=capture_insert,
        ),
        patch("app.payments.service.confirm_payment_paid"),
        patch("app.payments.repository.mark_event_processed"),
    ):
        webhook.handle_webhook(
            raw_body=b"{}",
            signature="ok",
            event_id="evt_hdr",
            payload={"event": "payment.captured"},
            headers={"X-Razorpay-Signature": "actual_secret_value"},
        )
    assert captured["headers"]["X-Razorpay-Signature"] == "[present]"


def test_webhook_marks_event_failed_on_processing_error():
    from app.payments.exceptions import WebhookTransientError

    with (
        patch(
            "app.payments.razorpay_client.verify_webhook_signature", return_value=True
        ),
        patch(
            "app.payments.repository.insert_payment_event",
            return_value={"id": "evt_fail"},
        ),
        patch(
            "app.payments.service.confirm_payment_paid",
            side_effect=RuntimeError("db down"),
        ),
        patch("app.payments.repository.mark_event_failed") as failed,
    ):
        with pytest.raises(WebhookTransientError) as exc:
            webhook.handle_webhook(
                raw_body=b"{}",
                signature="ok",
                event_id="evt_err",
                payload={
                    "event": "payment.captured",
                    "payload": {
                        "payment": {
                            "entity": {"id": "p", "order_id": "o", "amount": 99900}
                        }
                    },
                },
            )
        assert exc.value.status_code == 503
        failed.assert_called_once()


def test_webhook_payment_not_found_is_transient_503():
    from app.payments.exceptions import PaymentNotFoundError, WebhookTransientError

    with (
        patch(
            "app.payments.razorpay_client.verify_webhook_signature", return_value=True
        ),
        patch(
            "app.payments.repository.insert_payment_event",
            return_value={"id": "evt_nf"},
        ),
        patch(
            "app.payments.service.confirm_payment_paid",
            side_effect=PaymentNotFoundError(),
        ),
        patch("app.payments.repository.mark_event_failed") as failed,
    ):
        with pytest.raises(WebhookTransientError) as exc:
            webhook.handle_webhook(
                raw_body=b"{}",
                signature="ok",
                event_id="evt_nf",
                payload={
                    "event": "payment.captured",
                    "payload": {
                        "payment": {
                            "entity": {"id": "p", "order_id": "o", "amount": 99900}
                        }
                    },
                },
            )
        assert exc.value.status_code == 503
        failed.assert_called_once()


def test_webhook_permanent_error_does_not_raise_503():
    from app.payments.exceptions import PaymentAmountMismatchError

    with (
        patch(
            "app.payments.razorpay_client.verify_webhook_signature", return_value=True
        ),
        patch(
            "app.payments.repository.insert_payment_event",
            return_value={"id": "evt_amt"},
        ),
        patch(
            "app.payments.service.confirm_payment_paid",
            side_effect=PaymentAmountMismatchError(),
        ),
        patch("app.payments.repository.mark_event_failed") as failed,
    ):
        result = webhook.handle_webhook(
            raw_body=b"{}",
            signature="ok",
            event_id="evt_amt",
            payload={
                "event": "payment.captured",
                "payload": {
                    "payment": {
                        "entity": {"id": "p", "order_id": "o", "amount": 99900}
                    }
                },
            },
        )
    assert result == {"ok": True, "processing_failed": True}
    failed.assert_called_once()


def test_sequential_fallback_skips_insert_when_subscription_exists():
    from datetime import UTC, datetime, timedelta

    paid = {
        **_created_payment(order_id="order_fb"),
        "status": "paid",
    }
    existing_sub = {"id": "sub_1", "payment_id": paid["id"]}
    with (
        patch(
            "app.payments.repository.get_payment_by_order_id", return_value=paid
        ),
        patch(
            "app.payments.repository.list_subscriptions_for_payment",
            return_value=[existing_sub],
        ),
        patch("app.payments.repository.insert_subscription") as insert_sub,
        patch("app.payments.repository.mark_payment_status") as mark,
    ):
        out = repository._confirm_payment_paid_sequential(
            razorpay_order_id="order_fb",
            razorpay_payment_id="pay_fb",
            razorpay_signature=None,
            starts_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
    assert out["already_paid"] is True
    assert out["subscription_id"] == "sub_1"
    insert_sub.assert_not_called()
    mark.assert_not_called()


def test_insert_subscription_treats_unique_violation_as_success():
    from datetime import UTC, datetime, timedelta

    from app.payments import repository as repo

    existing = {"id": "sub_race", "payment_id": str(PAYMENT_ID)}
    with (
        patch("app.payments.repository._exec", side_effect=Exception("23505 unique")),
        patch(
            "app.payments.repository.list_subscriptions_for_payment",
            return_value=[existing],
        ),
    ):
        row = repo.insert_subscription(
            user_id=USER_ID,
            plan_id=PLAN_ID,
            payment_id=PAYMENT_ID,
            starts_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
    assert row["id"] == "sub_race"


def test_webhook_payment_failed_marks_payment():
    payment = {**_created_payment(), "status": "created"}
    with (
        patch(
            "app.payments.razorpay_client.verify_webhook_signature", return_value=True
        ),
        patch(
            "app.payments.repository.insert_payment_event",
            return_value={"id": "evt_pf"},
        ),
        patch(
            "app.payments.repository.get_payment_by_order_id", return_value=payment
        ),
        patch("app.payments.repository.mark_payment_status") as mark,
        patch("app.payments.repository.mark_event_processed") as processed,
    ):
        result = webhook.handle_webhook(
            raw_body=b"{}",
            signature="ok",
            event_id="evt_pf",
            payload={
                "event": "payment.failed",
                "payload": {"payment": {"entity": {"id": "p", "order_id": "order_x"}}},
            },
        )
        assert result == {"ok": True}
        mark.assert_called_once()
        processed.assert_called_once()


def test_webhook_refund_cancels_subscription():
    paid = {**_created_payment(), "status": "paid", "razorpay_payment_id": "pay_r"}
    with (
        patch(
            "app.payments.razorpay_client.verify_webhook_signature", return_value=True
        ),
        patch(
            "app.payments.repository.insert_payment_event",
            return_value={"id": "evt_rf"},
        ),
        patch(
            "app.payments.repository.get_payment_by_razorpay_payment_id",
            return_value=paid,
        ),
        patch("app.payments.repository.mark_payment_status") as mark,
        patch("app.payments.repository.cancel_subscription_for_payment") as cancel,
        patch("app.payments.repository.mark_event_processed"),
    ):
        result = webhook.handle_webhook(
            raw_body=b"{}",
            signature="ok",
            event_id="evt_rf",
            payload={
                "event": "refund.created",
                "payload": {"refund": {"entity": {"payment_id": "pay_r"}}},
            },
        )
        assert result == {"ok": True}
        mark.assert_called_once()
        cancel.assert_called_once_with(payment_id=paid["id"])


def test_confirm_payment_paid_rejects_amount_mismatch():
    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_created_payment(),
        ),
        patch("app.payments.service.repository.get_plan_by_id", return_value=_plan()),
    ):
        with pytest.raises(HTTPException) as exc:
            service.confirm_payment_paid(
                razorpay_order_id="order_x",
                razorpay_payment_id="pay_x",
                captured_amount=1,
            )
        assert exc.value.status_code == 400


def test_confirm_payment_paid_rejects_missing_amount():
    with (
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_created_payment(),
        ),
        patch("app.payments.service.repository.get_plan_by_id", return_value=_plan()),
    ):
        with pytest.raises(HTTPException) as exc:
            service.confirm_payment_paid(
                razorpay_order_id="order_x",
                razorpay_payment_id="pay_x",
                captured_amount=None,
            )
        assert exc.value.status_code == 400


def test_webhook_partial_refund_revokes_access():
    paid = {**_created_payment(), "status": "paid", "razorpay_payment_id": "pay_r"}
    with (
        patch(
            "app.payments.razorpay_client.verify_webhook_signature", return_value=True
        ),
        patch(
            "app.payments.repository.insert_payment_event",
            return_value={"id": "evt_prf"},
        ),
        patch(
            "app.payments.repository.get_payment_by_razorpay_payment_id",
            return_value=paid,
        ),
        patch("app.payments.repository.mark_payment_status") as mark,
        patch("app.payments.repository.cancel_subscription_for_payment") as cancel,
        patch("app.payments.repository.mark_event_processed"),
    ):
        result = webhook.handle_webhook(
            raw_body=b"{}",
            signature="ok",
            event_id="evt_prf",
            payload={
                "event": "refund.created",
                "payload": {
                    "refund": {
                        "entity": {
                            "payment_id": "pay_r",
                            "amount": 10000,
                        }
                    }
                },
            },
        )
        assert result == {"ok": True}
        mark.assert_called_once()
        cancel.assert_called_once_with(payment_id=paid["id"])


def test_create_order_rejects_guest_user():
    guest = UserPublic(
        id=USER_ID,
        email=None,
        full_name=None,
        phone=None,
        target_band=None,
        role="guest",
    )
    with pytest.raises(HTTPException) as exc:
        service.create_order(user=guest, plan_slug="premium_monthly")
    assert exc.value.status_code == 403


def test_get_plans_returns_active_plans():
    with (
        patch(
            "app.payments.service.repository.list_active_plans",
            return_value=[_plan()],
        ),
        patch("app.payments.razorpay_client.get_settings", return_value=_fake_settings()),
        patch("app.payments.razorpay_client.credentials_ready", return_value=True),
    ):
        resp = service.get_plans()
        assert len(resp.plans) == 1
        assert resp.plans[0].slug == "premium_monthly"
        assert resp.payments_enabled is True
        assert resp.checkout_test_mode is True


def test_create_order_disabled_when_flag_off():
    with patch(
        "app.payments.service.get_settings",
        return_value=_fake_settings(razorpay_enabled=False),
    ):
        with pytest.raises(HTTPException) as exc:
            service.create_order(user=_user(), plan_slug="premium_monthly")
        assert exc.value.status_code == 503


def test_get_plans_payments_disabled_without_keys():
    with (
        patch(
            "app.payments.service.repository.list_active_plans",
            return_value=[_plan()],
        ),
        patch(
            "app.payments.razorpay_client.get_settings",
            return_value=_fake_settings(razorpay_key_id=""),
        ),
    ):
        resp = service.get_plans()
        assert resp.payments_enabled is False


def _premium_access_user() -> "UserPublic":
    from app.auth.schemas import UserPublic

    return UserPublic(
        id=USER_ID,
        email="s@example.com",
        full_name="S",
        phone=None,
        target_band=7.0,
    )


def test_premium_mock_access_allows_diagnostic_without_subscription():
    from app.diagnostic.constants import DIAGNOSTIC_MOCK_TEST_ID
    from app.security.entitlements import assert_premium_mock_access

    user = _premium_access_user()
    with patch(
        "app.security.entitlements.has_active_subscription", return_value=False
    ):
        assert_premium_mock_access(user=user, mock_test_id=DIAGNOSTIC_MOCK_TEST_ID)


def test_premium_mock_access_blocks_m01_without_subscription():
    from uuid import UUID

    from app.mock_catalog.constants import M01_MOCK_TEST_ID
    from app.security.entitlements import assert_premium_mock_access

    user = _premium_access_user()
    with (
        patch(
            "app.security.entitlements.has_active_subscription", return_value=False
        ),
        patch(
            "app.security.mock_access.get_mock_access_flags",
            return_value={"is_free": False, "is_diagnostic": False},
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            assert_premium_mock_access(
                user=user, mock_test_id=UUID(M01_MOCK_TEST_ID)
            )
        assert exc.value.status_code == 402


def test_premium_mock_access_blocks_m02_without_subscription():
    from uuid import UUID

    from app.mock_catalog.constants import M02_MOCK_TEST_ID
    from app.security.entitlements import assert_premium_mock_access

    user = _premium_access_user()
    with (
        patch(
            "app.security.entitlements.has_active_subscription", return_value=False
        ),
        patch(
            "app.security.mock_access.get_mock_access_flags",
            return_value={"is_free": False, "is_diagnostic": False},
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            assert_premium_mock_access(
                user=user, mock_test_id=UUID(M02_MOCK_TEST_ID)
            )
        assert exc.value.status_code == 402


def test_premium_mock_access_blocks_unknown_mock_without_subscription():
    from uuid import UUID

    from app.security.entitlements import assert_premium_mock_access

    user = _premium_access_user()
    with (
        patch(
            "app.security.entitlements.has_active_subscription", return_value=False
        ),
        patch(
            "app.security.mock_access.get_mock_access_flags",
            return_value={"is_free": False, "is_diagnostic": False},
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            assert_premium_mock_access(
                user=user,
                mock_test_id=UUID("a0000000-0000-4000-8000-000000000099"),
            )
        assert exc.value.status_code == 402


def test_premium_mock_access_allows_is_free_without_subscription():
    from uuid import UUID

    from app.security.entitlements import assert_premium_mock_access

    user = _premium_access_user()
    with (
        patch(
            "app.security.entitlements.has_active_subscription", return_value=False
        ),
        patch(
            "app.security.mock_access.get_mock_access_flags",
            return_value={"is_free": True, "is_diagnostic": False},
        ),
    ):
        assert_premium_mock_access(
            user=user,
            mock_test_id=UUID("a0000000-0000-4000-8000-000000000099"),
        )


def test_enforce_premium_flags_skips_subscription_when_prefetched():
    """Gate RPC can pass subscription_active and avoid a second subscriptions read."""
    from unittest.mock import patch
    from uuid import UUID

    from app.security.entitlements import enforce_premium_mock_flags

    user = _premium_access_user()
    with patch(
        "app.security.entitlements.has_active_subscription"
    ) as has_sub:
        enforce_premium_mock_flags(
            user=user,
            mock_test_id=UUID("a0000000-0000-4000-8000-000000000001"),
            flags={"is_free": False, "is_diagnostic": False},
            subscription_active=True,
        )
        has_sub.assert_not_called()

    with (
        patch("app.security.entitlements.has_active_subscription") as has_sub,
        pytest.raises(HTTPException) as exc,
    ):
        enforce_premium_mock_flags(
            user=user,
            mock_test_id=UUID("a0000000-0000-4000-8000-000000000001"),
            flags={"is_free": False, "is_diagnostic": False},
            subscription_active=False,
        )
    assert exc.value.status_code == 402
    has_sub.assert_not_called()


def test_premium_mock_access_missing_mock_returns_404():
    from uuid import UUID

    from app.security.entitlements import assert_premium_mock_access

    user = _premium_access_user()
    with patch(
        "app.security.mock_access.get_mock_access_flags",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc:
            assert_premium_mock_access(
                user=user,
                mock_test_id=UUID("a0000000-0000-4000-8000-000000000099"),
            )
        assert exc.value.status_code == 404


def test_premium_mock_access_allows_paid_mock_with_subscription():
    from uuid import UUID

    from app.mock_catalog.constants import M01_MOCK_TEST_ID
    from app.security.entitlements import assert_premium_mock_access

    user = _premium_access_user()
    with (
        patch(
            "app.security.entitlements.has_active_subscription", return_value=True
        ),
        patch(
            "app.security.mock_access.get_mock_access_flags",
            return_value={"is_free": False, "is_diagnostic": False},
        ),
    ):
        assert_premium_mock_access(user=user, mock_test_id=UUID(M01_MOCK_TEST_ID))


def test_receipt_default_length_is_32_chars():
    receipt = secrets.token_hex(16)
    assert len(receipt) == 32


_ = (MagicMock, EVENT_PROCESSED)
