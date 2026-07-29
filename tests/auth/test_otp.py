"""Unit tests for phone OTP create/verify and production guards."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.auth.constants import OTP_PURPOSE_LOGIN, OTP_RESEND_COOLDOWN_SECONDS
from app.auth.otp import OtpError, create_and_send_otp, verify_otp_code
from app.auth.utils import hash_otp, utcnow


def _settings(**kwargs):
    defaults = {
        "app_env": "development",
        "auth_demo_otp": "",
        "auth_demo_otp_enabled": True,
        "auth_open_otp": False,
        "msg91_auth_key": "key",
        "msg91_template_id": "tmpl",
        "phone_otp_enabled": True,
    }
    defaults.update(kwargs)
    return MagicMock(**defaults)


def _supabase_chain(execute_data=None):
    mock_sb = MagicMock()
    result = MagicMock()
    result.data = execute_data if execute_data is not None else []
    # Support select/insert/update chains ending in execute()
    table = mock_sb.table.return_value
    for method in ("select", "insert", "update", "eq", "is_", "order", "limit"):
        getattr(table, method).return_value = table
    table.execute.return_value = result
    return mock_sb, result


def test_create_and_send_otp_rejects_missing_msg91_in_production():
    mock_sb, _ = _supabase_chain([])
    settings = _settings(
        app_env="production",
        msg91_auth_key="",
        msg91_template_id="",
        auth_demo_otp_enabled=False,
    )
    with (
        patch("app.auth.otp.get_settings", return_value=settings),
        patch("app.auth.otp.get_supabase", return_value=mock_sb),
    ):
        with pytest.raises(OtpError) as exc:
            asyncio.run(create_and_send_otp(phone="9876543210"))
    assert exc.value.status_code == 503
    assert "MSG91" in exc.value.message


def test_create_and_send_otp_enforces_resend_cooldown():
    now = utcnow()
    recent = (now - timedelta(seconds=10)).isoformat()
    mock_sb, result = _supabase_chain([{"created_at": recent}])
    settings = _settings()
    with (
        patch("app.auth.otp.get_settings", return_value=settings),
        patch("app.auth.otp.get_supabase", return_value=mock_sb),
    ):
        with pytest.raises(OtpError) as exc:
            asyncio.run(create_and_send_otp(phone="9876543210"))
    assert exc.value.status_code == 429
    assert "wait" in exc.value.message.lower()
    assert OTP_RESEND_COOLDOWN_SECONDS >= 60


def test_create_and_send_otp_success_returns_demo_hint():
    mock_sb, result = _supabase_chain([])
    # First execute: cooldown select (empty); second: insert
    result.data = []
    settings = _settings(auth_demo_otp="1234")
    with (
        patch("app.auth.otp.get_settings", return_value=settings),
        patch("app.auth.otp.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.sms.send_otp_sms_digits",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        hint = asyncio.run(create_and_send_otp(phone="9876543210"))
    assert hint is not None
    assert "Demo mode" in hint
    mock_sb.table.assert_called()


def test_verify_otp_code_accepts_demo_otp():
    mock_sb, result = _supabase_chain([{"id": str(uuid4())}])
    settings = _settings(auth_demo_otp="1234")
    with (
        patch("app.auth.otp.get_settings", return_value=settings),
        patch("app.auth.otp.get_supabase", return_value=mock_sb),
    ):
        asyncio.run(
            verify_otp_code(
                phone="9876543210",
                code="1234",
                purpose=OTP_PURPOSE_LOGIN,
            )
        )


def test_verify_otp_code_rejects_invalid():
    now = utcnow()
    mock_sb, result = _supabase_chain(
        [
            {
                "id": str(uuid4()),
                "attempts": 0,
                "max_attempts": 5,
                "expires_at": (now + timedelta(minutes=5)).isoformat(),
                "code_hash": hash_otp("1111"),
            }
        ]
    )
    settings = _settings(auth_demo_otp="", auth_open_otp=False)
    with (
        patch("app.auth.otp.get_settings", return_value=settings),
        patch("app.auth.otp.get_supabase", return_value=mock_sb),
    ):
        with pytest.raises(OtpError) as exc:
            asyncio.run(
                verify_otp_code(
                    phone="9876543210",
                    code="9999",
                    purpose=OTP_PURPOSE_LOGIN,
                )
            )
    assert exc.value.status_code == 401
    assert "Invalid" in exc.value.message
