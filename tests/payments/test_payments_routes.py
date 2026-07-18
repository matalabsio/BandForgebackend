"""HTTP functional tests for /api/payments/* routes."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from razorpay.errors import BadRequestError

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.main import app

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


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def authed_client():
    app.dependency_overrides[get_current_user] = lambda: _user()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_plans_route_public(client: TestClient):
    with (
        patch(
            "app.payments.service.repository.list_active_plans",
            return_value=[_plan()],
        ),
        patch("app.payments.razorpay_client.credentials_ready", return_value=True),
    ):
        res = client.get("/api/payments/plans")
    assert res.status_code == 200
    body = res.json()
    assert body["payments_enabled"] is True
    assert body["checkout_test_mode"] is True
    assert len(body["plans"]) == 1
    assert body["plans"][0]["slug"] == "premium_monthly"


def test_create_order_requires_auth(client: TestClient):
    res = client.post(
        "/api/payments/create-order",
        json={"plan_slug": "premium_monthly"},
    )
    assert res.status_code == 401


def _persisted_payment(order_id: str) -> dict:
    return {
        "id": str(PAYMENT_ID),
        "user_id": str(USER_ID),
        "plan_id": str(PLAN_ID),
        "status": "created",
        "amount": 99900,
        "currency": "INR",
        "razorpay_order_id": order_id,
    }


def test_create_order_happy_path(authed_client: TestClient):
    order_id = "order_route_test"
    with (
        patch("app.payments.service.get_settings", return_value=_fake_settings()),
        patch("app.payments.service.repository.get_plan_by_slug", return_value=_plan()),
        patch(
            "app.payments.service.razorpay_client.create_order",
            return_value={"id": order_id},
        ),
        patch(
            "app.payments.service.repository.insert_payment",
            return_value={"id": str(PAYMENT_ID)},
        ),
        patch(
            "app.payments.service.repository.count_payments_by_order_id",
            return_value=1,
        ),
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_persisted_payment(order_id),
        ),
        patch("app.payments.service.secrets.token_hex", return_value="a" * 32),
    ):
        res = authed_client.post(
            "/api/payments/create-order",
            json={"plan_slug": "premium_monthly"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["order_id"] == order_id
    assert body["key_id"] == "rzp_test_key"
    assert body["checkout_contact"]["contact"] == "+919876543210"
    assert body["amount"] == 99900
    assert body.get("checkout_config_id") in (None, "")


def test_create_order_includes_checkout_config_id_in_response(authed_client: TestClient):
    order_id = "order_route_config"
    with (
        patch(
            "app.payments.service.get_settings",
            return_value=_fake_settings(razorpay_checkout_config_id="config_route_123"),
        ),
        patch("app.payments.service.repository.get_plan_by_slug", return_value=_plan()),
        patch(
            "app.payments.service.razorpay_client.create_order",
            return_value={"id": order_id},
        ),
        patch(
            "app.payments.service.repository.insert_payment",
            return_value={"id": str(PAYMENT_ID)},
        ),
        patch(
            "app.payments.service.repository.count_payments_by_order_id",
            return_value=1,
        ),
        patch(
            "app.payments.service.repository.get_payment_by_order_id",
            return_value=_persisted_payment(order_id),
        ),
        patch("app.payments.service.secrets.token_hex", return_value="a" * 32),
    ):
        res = authed_client.post(
            "/api/payments/create-order",
            json={"plan_slug": "premium_monthly"},
        )
    assert res.status_code == 200
    assert res.json()["checkout_config_id"] == "config_route_123"


def test_create_order_unknown_plan(authed_client: TestClient):
    with (
        patch("app.payments.service.get_settings", return_value=_fake_settings()),
        patch("app.payments.service.repository.get_plan_by_slug", return_value=None),
    ):
        res = authed_client.post(
            "/api/payments/create-order",
            json={"plan_slug": "nope"},
        )
    assert res.status_code == 404


def test_create_order_razorpay_auth_failure(authed_client: TestClient):
    fake_client = MagicMock()
    fake_client.order.create.side_effect = BadRequestError("Authentication failed")
    with (
        patch("app.payments.service.get_settings", return_value=_fake_settings()),
        patch("app.payments.service.repository.get_plan_by_slug", return_value=_plan()),
        patch("app.payments.razorpay_client._client", return_value=fake_client),
        patch("app.payments.service.secrets.token_hex", return_value="a" * 32),
    ):
        res = authed_client.post(
            "/api/payments/create-order",
            json={"plan_slug": "premium_monthly"},
        )
    assert res.status_code == 503
    assert "authentication failed" in res.json()["detail"].lower()


def test_verify_route_bad_signature(authed_client: TestClient):
    with (
        patch("app.payments.service.get_settings", return_value=_fake_settings()),
        patch(
            "app.payments.service.razorpay_client.verify_payment_signature",
            return_value=False,
        ),
    ):
        res = authed_client.post(
            "/api/payments/verify",
            json={
                "razorpay_order_id": "order_x",
                "razorpay_payment_id": "pay_x",
                "razorpay_signature": "bad",
            },
        )
    assert res.status_code == 400


def test_webhook_invalid_signature(client: TestClient):
    with patch(
        "app.payments.razorpay_client.verify_webhook_signature",
        return_value=False,
    ):
        res = client.post(
            "/api/payments/webhook",
            content=json.dumps({"event": "payment.captured"}),
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": "invalid",
            },
        )
    assert res.status_code == 400


@pytest.mark.integration
def test_razorpay_live_credentials_probe():
    if os.environ.get("RAZORPAY_LIVE_TEST", "").strip() not in ("1", "true", "yes"):
        pytest.skip("Set RAZORPAY_LIVE_TEST=1 to run live Razorpay credential probe")

    from app.config import reload_settings
    from app.payments.razorpay_client import probe_credentials

    reload_settings()
    ok, msg = probe_credentials()
    assert ok, f"Razorpay credential probe failed: {msg}"
