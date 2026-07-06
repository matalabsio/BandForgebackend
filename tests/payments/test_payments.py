"""Payments module tests: data minimization, signatures, idempotency, stacking."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.auth.schemas import UserPublic
from app.payments import razorpay_client, service, webhook
from app.payments.constants import EVENT_PROCESSED
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


def _created_payment() -> dict:
    return {
        "id": str(PAYMENT_ID),
        "user_id": str(USER_ID),
        "plan_id": str(PLAN_ID),
        "status": "created",
        "amount": 99900,
    }


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
        patch("app.payments.service.repository.insert_payment", return_value={"id": str(PAYMENT_ID)}),
        patch("app.payments.service.secrets.token_hex", return_value="a" * 32),
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
        patch("app.payments.service.repository.insert_payment", return_value={"id": str(PAYMENT_ID)}),
        patch("app.payments.service.secrets.token_hex", return_value="a" * 32),
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
        patch("app.payments.service.repository.insert_payment", return_value={"id": str(PAYMENT_ID)}),
        patch("app.payments.service.secrets.token_hex", return_value="a" * 32),
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
        patch("app.payments.service.get_subscription", return_value=active_sub),
        patch("app.payments.service.repository.confirm_payment_paid_bundle") as bundle,
    ):
        result = service.confirm_payment_paid(
            razorpay_order_id="order_x",
            razorpay_payment_id="pay_x",
        )
        assert result.is_active
        bundle.assert_not_called()


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
    ):
        service.confirm_payment_paid(
            razorpay_order_id="order_x",
            razorpay_payment_id="pay_x",
            razorpay_signature="sig",
        )
        bundle.assert_called_once()
        kwargs = bundle.call_args.kwargs
        assert kwargs["razorpay_order_id"] == "order_x"
        assert kwargs["razorpay_payment_id"] == "pay_x"


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


def test_webhook_payment_captured_uses_confirm_payment_paid():
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
            captured_amount=None,
        )
        processed.assert_called_once()


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
        result = webhook.handle_webhook(
            raw_body=b"{}",
            signature="ok",
            event_id="evt_err",
            payload={
                "event": "payment.captured",
                "payload": {
                    "payment": {"entity": {"id": "p", "order_id": "o", "amount": 99900}}
                },
            },
        )
        assert result == {"ok": True, "processing_failed": True}
        failed.assert_called_once()


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


def test_premium_mock_access_blocks_m02_without_subscription():
    from uuid import UUID

    from app.auth.schemas import UserPublic
    from app.mock_catalog.constants import M02_MOCK_TEST_ID
    from app.security.entitlements import assert_premium_mock_access

    user = UserPublic(
        id=USER_ID,
        email="s@example.com",
        full_name="S",
        phone=None,
        target_band=7.0,
    )
    with patch(
        "app.security.entitlements.has_active_subscription", return_value=False
    ):
        with pytest.raises(HTTPException) as exc:
            assert_premium_mock_access(
                user=user, mock_test_id=UUID(M02_MOCK_TEST_ID)
            )
        assert exc.value.status_code == 402


def test_receipt_default_length_is_32_chars():
    receipt = secrets.token_hex(16)
    assert len(receipt) == 32


_ = (MagicMock, EVENT_PROCESSED)
