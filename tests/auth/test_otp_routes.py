"""API tests for /auth/send-otp and /auth/verify-otp."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.constants import ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE
from app.auth.routes import router as auth_router
from app.auth.schemas import AuthResponse, UserPublic
from app.security import rate_limit as rl

PHONE = "9876543210"
USER_ID = UUID("33333333-3333-4333-8333-333333333333")


@pytest.fixture(autouse=True)
def _clear_rate_limits():
    rl.reset_rate_limit_state_for_tests()
    yield
    rl.reset_rate_limit_state_for_tests()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(auth_router)
    return TestClient(app)


def _auth_response() -> AuthResponse:
    return AuthResponse(
        user=UserPublic(
            id=USER_ID,
            email=None,
            full_name=None,
            phone=f"+91{PHONE}",
            email_verified=False,
            phone_verified=True,
            role="student",
            is_active=True,
        ),
        access_token="access-token-test",
        token_type="bearer",
        expires_in=900,
    )


def test_send_otp_disabled_returns_503(client: TestClient):
    settings = MagicMock(phone_otp_enabled=False)
    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch("app.security.rate_limit._redis_allow", return_value=None),
    ):
        resp = client.post("/auth/send-otp", json={"phone": PHONE})
    assert resp.status_code == 503
    assert "not enabled" in resp.json()["detail"].lower()


def test_send_otp_enabled_returns_message(client: TestClient):
    settings = MagicMock(phone_otp_enabled=True)
    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch(
            "app.auth.service.create_and_send_otp",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("app.security.rate_limit._redis_allow", return_value=None),
    ):
        resp = client.post("/auth/send-otp", json={"phone": PHONE})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["message"] == "OTP sent."


def test_send_otp_invalid_phone(client: TestClient):
    resp = client.post("/auth/send-otp", json={"phone": "12345"})
    assert resp.status_code == 422


def test_verify_otp_sets_cookies(client: TestClient):
    settings = MagicMock(phone_otp_enabled=True, app_env="development")
    auth = _auth_response()
    refresh = "refresh-token-test"
    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch("app.auth.routes.get_settings", return_value=settings),
        patch(
            "app.auth.service.verify_phone_otp",
            new_callable=AsyncMock,
            return_value=(auth, refresh, str(uuid4())),
        ),
        patch("app.security.rate_limit._redis_allow", return_value=None),
    ):
        resp = client.post(
            "/auth/verify-otp",
            json={"phone": PHONE, "code": "1234"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] == "access-token-test"
    assert body["refresh_token"] == refresh
    assert body["user"]["phone_verified"] is True
    assert ACCESS_TOKEN_COOKIE in resp.cookies
    assert REFRESH_TOKEN_COOKIE in resp.cookies


def test_verify_otp_disabled_returns_503(client: TestClient):
    settings = MagicMock(phone_otp_enabled=False, app_env="development")
    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch("app.auth.routes.get_settings", return_value=settings),
        patch("app.security.rate_limit._redis_allow", return_value=None),
    ):
        resp = client.post(
            "/auth/verify-otp",
            json={"phone": PHONE, "code": "1234"},
        )
    assert resp.status_code == 503


def test_verify_otp_rejects_six_digit_code(client: TestClient):
    resp = client.post(
        "/auth/verify-otp",
        json={"phone": PHONE, "code": "123456"},
    )
    assert resp.status_code == 422
