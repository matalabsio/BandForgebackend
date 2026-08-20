"""API tests for /auth/send-otp and /auth/verify-otp."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.constants import ACCESS_TOKEN_COOKIE, OTP_RATE_LIMIT_PER_PHONE, REFRESH_TOKEN_COOKIE
from app.auth.routes import router as auth_router
from app.auth.schemas import AuthResponse, UserPublic
from app.auth import service
from app.security import rate_limit as rl

PHONE = "9876543210"
USER_ID = UUID("33333333-3333-4333-8333-333333333333")
ADMIN_USER_ID = UUID("66666666-6666-4666-8666-666666666666")


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


def _mock_phone_users_sb(*, select_rows: list, write_rows: list | None = None):
    mock_sb = MagicMock()
    table = mock_sb.table.return_value
    for method in ("select", "insert", "update", "eq", "limit"):
        getattr(table, method).return_value = table

    call = {"n": 0}

    def execute():
        call["n"] += 1
        result = MagicMock()
        if call["n"] == 1:
            result.data = select_rows
        else:
            result.data = write_rows or []
        return result

    table.execute.side_effect = execute
    return mock_sb, table


def test_verify_phone_otp_rejects_admin_user():
    settings = MagicMock(phone_otp_enabled=True)
    existing_row = {
        "id": str(ADMIN_USER_ID),
        "email": "admin@example.com",
        "full_name": "Admin User",
        "phone": f"+91{PHONE}",
        "email_verified_at": None,
        "phone_verified_at": None,
        "role": "admin",
        "is_active": True,
    }
    mock_sb, table = _mock_phone_users_sb(select_rows=[existing_row])

    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch("app.auth.service.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.service.verify_otp_code",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.auth.service._issue_tokens",
            new_callable=AsyncMock,
        ) as issue_tokens,
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                service.verify_phone_otp(phone_digits=PHONE, code="1234")
            )

    assert exc.value.status_code == 403
    assert "student" in exc.value.detail.lower()
    table.update.assert_not_called()
    table.insert.assert_not_called()
    issue_tokens.assert_not_awaited()


def test_send_otp_ip_rate_limits_distinct_phones(client: TestClient):
    settings = MagicMock(phone_otp_enabled=True, app_env="production")
    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch(
            "app.auth.service.create_and_send_otp",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("app.security.rate_limit._redis_allow", return_value=None),
        patch("app.security.rate_limit.rate_limit_fail_closed", return_value=False),
    ):
        for i in range(OTP_RATE_LIMIT_PER_PHONE):
            resp = client.post(
                "/auth/send-otp",
                json={"phone": f"987654321{i}"},
            )
            assert resp.status_code == 200
        resp = client.post(
            "/auth/send-otp",
            json={"phone": "9876543299"},
        )
    assert resp.status_code == 429
    assert "address" in resp.json()["detail"].lower()
