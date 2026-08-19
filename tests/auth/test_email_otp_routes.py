"""API tests for /auth/send-email-otp and /auth/verify-email-otp."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.constants import (
    ACCESS_TOKEN_COOKIE,
    OTP_RATE_LIMIT_PER_PHONE,
    REFRESH_TOKEN_COOKIE,
)
from app.auth.otp import OtpError
from app.auth.routes import router as auth_router
from app.auth.schemas import AuthResponse, UserPublic
from app.auth import service
from app.security import rate_limit as rl

EMAIL = "student@example.com"
GOOGLE_USER_ID = UUID("44444444-4444-4444-8444-444444444444")
NEW_USER_ID = UUID("55555555-5555-4555-8555-555555555555")
ADMIN_USER_ID = UUID("66666666-6666-4666-8666-666666666666")


def _mock_users_sb(*, select_rows: list, write_rows: list | None = None):
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


def _auth_response(*, user_id: UUID, email: str, email_verified: bool) -> AuthResponse:
    return AuthResponse(
        user=UserPublic(
            id=user_id,
            email=email,
            full_name="Student",
            phone=None,
            email_verified=email_verified,
            phone_verified=False,
            role="student",
            is_active=True,
        ),
        access_token="access-token-test",
        token_type="bearer",
        expires_in=900,
    )


def test_send_email_otp_disabled_returns_503(client: TestClient):
    settings = MagicMock(email_otp_enabled=False)
    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch("app.security.rate_limit._redis_allow", return_value=None),
    ):
        resp = client.post("/auth/send-email-otp", json={"email": EMAIL})
    assert resp.status_code == 503
    assert "not enabled" in resp.json()["detail"].lower()


def test_verify_email_otp_disabled_returns_503(client: TestClient):
    settings = MagicMock(email_otp_enabled=False, app_env="development")
    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch("app.auth.routes.get_settings", return_value=settings),
        patch("app.security.rate_limit._redis_allow", return_value=None),
    ):
        resp = client.post(
            "/auth/verify-email-otp",
            json={"email": EMAIL, "code": "123456"},
        )
    assert resp.status_code == 503


def test_send_email_otp_enabled_returns_message(client: TestClient):
    settings = MagicMock(email_otp_enabled=True, app_env="production")
    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch(
            "app.auth.service.create_and_send_email_otp",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("app.security.rate_limit._redis_allow", return_value=None),
    ):
        resp = client.post("/auth/send-email-otp", json={"email": EMAIL})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["message"] == "OTP sent."
    assert "123456" not in body["message"]


def test_send_email_otp_normalizes_email(client: TestClient):
    settings = MagicMock(email_otp_enabled=True, app_env="production")
    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch(
            "app.auth.service.create_and_send_email_otp",
            new_callable=AsyncMock,
            return_value=None,
        ) as send_otp,
        patch("app.security.rate_limit._redis_allow", return_value=None),
    ):
        resp = client.post(
            "/auth/send-email-otp",
            json={"email": "  Student@Example.COM "},
        )
    assert resp.status_code == 200
    send_otp.assert_awaited_once_with(email="student@example.com", purpose="login")


def test_send_email_otp_invalid_email(client: TestClient):
    resp = client.post("/auth/send-email-otp", json={"email": "not-an-email"})
    assert resp.status_code == 422


def test_verify_email_otp_propagates_invalid_code(client: TestClient):
    settings = MagicMock(email_otp_enabled=True, app_env="development")
    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch("app.auth.routes.get_settings", return_value=settings),
        patch(
            "app.auth.service.verify_email_otp_code",
            new_callable=AsyncMock,
            side_effect=OtpError("Invalid OTP.", 401),
        ),
        patch("app.security.rate_limit._redis_allow", return_value=None),
    ):
        resp = client.post(
            "/auth/verify-email-otp",
            json={"email": EMAIL, "code": "000000"},
        )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid OTP."


def test_verify_email_otp_propagates_expired_code(client: TestClient):
    settings = MagicMock(email_otp_enabled=True, app_env="development")
    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch("app.auth.routes.get_settings", return_value=settings),
        patch(
            "app.auth.service.verify_email_otp_code",
            new_callable=AsyncMock,
            side_effect=OtpError("OTP expired. Request a new code.", 401),
        ),
        patch("app.security.rate_limit._redis_allow", return_value=None),
    ):
        resp = client.post(
            "/auth/verify-email-otp",
            json={"email": EMAIL, "code": "123456"},
        )
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


def test_verify_email_otp_rejects_non_six_digit_code(client: TestClient):
    resp = client.post(
        "/auth/verify-email-otp",
        json={"email": EMAIL, "code": "1234"},
    )
    assert resp.status_code == 422


def test_verify_email_otp_sets_cookies(client: TestClient):
    settings = MagicMock(email_otp_enabled=True, app_env="development")
    auth = _auth_response(user_id=NEW_USER_ID, email=EMAIL, email_verified=True)
    refresh = "refresh-token-test"
    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch("app.auth.routes.get_settings", return_value=settings),
        patch(
            "app.auth.service.verify_email_otp",
            new_callable=AsyncMock,
            return_value=(auth, refresh, str(uuid4())),
        ),
        patch("app.security.rate_limit._redis_allow", return_value=None),
    ):
        resp = client.post(
            "/auth/verify-email-otp",
            json={"email": EMAIL, "code": "123456"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] == "access-token-test"
    assert body["refresh_token"] == refresh
    assert body["user"]["email_verified"] is True
    assert ACCESS_TOKEN_COOKIE in resp.cookies
    assert REFRESH_TOKEN_COOKIE in resp.cookies


def test_verify_email_otp_creates_student_user():
    settings = MagicMock(email_otp_enabled=True)
    fixed_now = datetime(2026, 8, 19, 6, 0, tzinfo=UTC)
    now = fixed_now.isoformat()
    mock_sb, table = _mock_users_sb(
        select_rows=[],
        write_rows=[
            {
                "id": str(NEW_USER_ID),
                "email": EMAIL,
                "full_name": None,
                "phone": None,
                "email_verified_at": now,
                "phone_verified_at": None,
                "role": "student",
                "is_active": True,
            }
        ],
    )

    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch("app.auth.service.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.service.verify_email_otp_code",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.auth.service._issue_tokens",
            new_callable=AsyncMock,
            return_value=("access", "refresh", str(uuid4())),
        ),
        patch("app.auth.service.utcnow", return_value=fixed_now),
    ):
        auth, refresh, _ = asyncio.run(
            service.verify_email_otp(email=EMAIL, code="123456")
        )

    table.insert.assert_called_once()
    insert_payload = table.insert.call_args.args[0]
    assert insert_payload["email"] == EMAIL
    assert insert_payload["email_verified_at"] == now
    assert auth.user.id == NEW_USER_ID
    assert auth.user.email_verified is True
    assert refresh == "refresh"


def test_verify_email_otp_reuses_existing_google_user_without_insert():
    settings = MagicMock(email_otp_enabled=True)
    fixed_now = datetime(2026, 8, 19, 6, 0, tzinfo=UTC)
    now = fixed_now.isoformat()
    existing_row = {
        "id": str(GOOGLE_USER_ID),
        "email": EMAIL,
        "full_name": "Google Student",
        "phone": None,
        "google_id": "google-sub-123",
        "email_verified_at": None,
        "phone_verified_at": None,
        "role": "student",
        "is_active": True,
    }
    mock_sb, table = _mock_users_sb(
        select_rows=[existing_row],
        write_rows=[{"id": str(GOOGLE_USER_ID)}],
    )

    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch("app.auth.service.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.service.verify_email_otp_code",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.auth.service._issue_tokens",
            new_callable=AsyncMock,
            return_value=("access", "refresh", str(uuid4())),
        ),
        patch("app.auth.service.utcnow", return_value=fixed_now),
    ):
        auth, _, _ = asyncio.run(
            service.verify_email_otp(email=EMAIL, code="123456")
        )

    table.insert.assert_not_called()
    table.update.assert_called_once()
    assert auth.user.id == GOOGLE_USER_ID
    assert auth.user.email_verified is True


def test_verify_email_otp_rejects_admin_user():
    settings = MagicMock(email_otp_enabled=True)
    existing_row = {
        "id": str(ADMIN_USER_ID),
        "email": EMAIL,
        "full_name": "Admin User",
        "phone": None,
        "email_verified_at": None,
        "phone_verified_at": None,
        "role": "admin",
        "is_active": True,
    }
    mock_sb, table = _mock_users_sb(select_rows=[existing_row])

    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch("app.auth.service.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.service.verify_email_otp_code",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.auth.service._issue_tokens",
            new_callable=AsyncMock,
        ) as issue_tokens,
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(service.verify_email_otp(email=EMAIL, code="123456"))

    assert exc.value.status_code == 403
    assert "student" in exc.value.detail.lower()
    table.update.assert_not_called()
    table.insert.assert_not_called()
    issue_tokens.assert_not_awaited()


def test_verify_email_otp_rejects_deactivated_user():
    settings = MagicMock(email_otp_enabled=True)
    existing_row = {
        "id": str(GOOGLE_USER_ID),
        "email": EMAIL,
        "full_name": "Inactive Student",
        "phone": None,
        "email_verified_at": None,
        "phone_verified_at": None,
        "role": "student",
        "is_active": False,
    }
    mock_sb, table = _mock_users_sb(select_rows=[existing_row])

    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch("app.auth.service.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.service.verify_email_otp_code",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.auth.service._issue_tokens",
            new_callable=AsyncMock,
        ) as issue_tokens,
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(service.verify_email_otp(email=EMAIL, code="123456"))

    assert exc.value.status_code == 403
    assert "deactivated" in exc.value.detail.lower()
    table.insert.assert_not_called()
    issue_tokens.assert_not_awaited()


def test_verify_email_otp_normalizes_direct_service_input():
    settings = MagicMock(email_otp_enabled=True)
    raw_email = "  Student@Example.COM "
    fixed_now = datetime(2026, 8, 19, 6, 0, tzinfo=UTC)
    now = fixed_now.isoformat()
    mock_sb, table = _mock_users_sb(
        select_rows=[],
        write_rows=[
            {
                "id": str(NEW_USER_ID),
                "email": "student@example.com",
                "full_name": None,
                "phone": None,
                "email_verified_at": now,
                "phone_verified_at": None,
                "role": "student",
                "is_active": True,
            }
        ],
    )

    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch("app.auth.service.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.service.verify_email_otp_code",
            new_callable=AsyncMock,
            return_value=None,
        ) as verify_code,
        patch(
            "app.auth.service._issue_tokens",
            new_callable=AsyncMock,
            return_value=("access", "refresh", str(uuid4())),
        ),
        patch("app.auth.service.utcnow", return_value=fixed_now),
    ):
        asyncio.run(service.verify_email_otp(email=raw_email, code="123456"))

    verify_code.assert_awaited_once_with(
        email="student@example.com", code="123456", purpose="login"
    )
    insert_payload = table.insert.call_args.args[0]
    assert insert_payload["email"] == "student@example.com"


def test_send_email_otp_ip_rate_limits_distinct_emails(client: TestClient):
    settings = MagicMock(email_otp_enabled=True, app_env="production")
    with (
        patch("app.auth.service.get_settings", return_value=settings),
        patch(
            "app.auth.service.create_and_send_email_otp",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("app.security.rate_limit._redis_allow", return_value=None),
        patch("app.security.rate_limit.rate_limit_fail_closed", return_value=False),
    ):
        for i in range(OTP_RATE_LIMIT_PER_PHONE):
            resp = client.post(
                "/auth/send-email-otp",
                json={"email": f"user{i}@example.com"},
            )
            assert resp.status_code == 200
        resp = client.post(
            "/auth/send-email-otp",
            json={"email": "another@example.com"},
        )
    assert resp.status_code == 429
    assert "address" in resp.json()["detail"].lower()
