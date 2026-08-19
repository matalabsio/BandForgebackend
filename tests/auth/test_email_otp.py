"""Unit tests for email OTP create/verify primitives."""

from __future__ import annotations

import asyncio
import re
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.auth.constants import EMAIL_OTP_LENGTH, OTP_PURPOSE_LOGIN, OTP_RESEND_COOLDOWN_SECONDS
from app.auth.email_otp import (
    create_and_send_email_otp,
    generate_email_otp_code,
    verify_email_otp_code,
)
from app.auth.otp import OtpError
from app.auth.utils import hash_otp, normalize_email, utcnow

EMAIL = "student@example.com"
NORMALIZED = "student@example.com"


def _settings(**kwargs):
    defaults = {
        "app_env": "development",
        "auth_demo_otp": "",
        "auth_demo_otp_enabled": True,
        "auth_open_otp": False,
        "resend_api_key": "re_test",
        "email_from": "BandForge <noreply@example.com>",
    }
    defaults.update(kwargs)
    return MagicMock(**defaults)


def _supabase_chain(execute_data=None):
    mock_sb = MagicMock()
    result = MagicMock()
    result.data = execute_data if execute_data is not None else []
    table = mock_sb.table.return_value
    for method in ("select", "insert", "update", "eq", "is_", "order", "limit", "gt"):
        getattr(table, method).return_value = table
    table.execute.return_value = result
    return mock_sb, result


def _mock_rpc(*, create_data=None, increment_data=None):
    mock_sb = MagicMock()

    def rpc(name, params):
        chain = MagicMock()
        payload = MagicMock()
        if name == "create_email_otp_verification":
            payload.data = create_data
        elif name == "increment_email_otp_attempt":
            payload.data = increment_data
        else:
            payload.data = None
        chain.execute.return_value = payload
        return chain

    mock_sb.rpc.side_effect = rpc
    table = mock_sb.table.return_value
    for method in ("select", "update", "eq", "is_", "order", "limit", "gt"):
        getattr(table, method).return_value = table
    return mock_sb


def test_generate_email_otp_code_is_six_digits():
    for _ in range(20):
        code = generate_email_otp_code()
        assert len(code) == EMAIL_OTP_LENGTH
        assert re.fullmatch(r"\d{6}", code)


def test_normalize_email_lowercases_and_trims():
    assert normalize_email("  Student@Example.COM ") == "student@example.com"


def test_create_and_send_email_otp_rejects_empty_email():
    settings = _settings()
    mock_sb = _mock_rpc(
        create_data={"created": True, "verification_id": str(uuid4())},
    )
    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
    ):
        with pytest.raises(OtpError) as exc:
            asyncio.run(create_and_send_email_otp(email="   "))
    assert exc.value.status_code == 400
    assert "Email is required" in exc.value.message
    mock_sb.rpc.assert_not_called()


def test_verify_email_otp_code_rejects_empty_email():
    settings = _settings()
    mock_sb, _ = _supabase_chain([])
    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
    ):
        with pytest.raises(OtpError) as exc:
            asyncio.run(verify_email_otp_code(email="", code="123456"))
    assert exc.value.status_code == 400
    assert "Email is required" in exc.value.message
    mock_sb.table.assert_not_called()


def test_create_and_send_email_otp_stores_hash_only():
    record_id = str(uuid4())
    mock_sb = _mock_rpc(
        create_data={"created": True, "verification_id": record_id},
    )
    settings = _settings()
    rpc_params = {}

    def capture_rpc(name, params):
        rpc_params["name"] = name
        rpc_params["params"] = params
        chain = MagicMock()
        payload = MagicMock()
        payload.data = {"created": True, "verification_id": record_id}
        chain.execute.return_value = payload
        return chain

    mock_sb.rpc.side_effect = capture_rpc

    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.email.send_login_otp_email",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.auth.email_otp.generate_email_otp_code",
            return_value="654321",
        ),
    ):
        asyncio.run(create_and_send_email_otp(email=EMAIL))

    assert rpc_params["name"] == "create_email_otp_verification"
    assert rpc_params["params"]["p_email"] == NORMALIZED
    assert rpc_params["params"]["p_code_hash"] == hash_otp("654321")
    assert "654321" not in rpc_params["params"].values()
    assert rpc_params["params"]["p_max_attempts"] == 5


def test_create_and_send_email_otp_normalizes_email_on_write():
    record_id = str(uuid4())
    mock_sb = _mock_rpc(
        create_data={"created": True, "verification_id": record_id},
    )
    settings = _settings()
    rpc_params = {}

    def capture_rpc(name, params):
        rpc_params["params"] = params
        chain = MagicMock()
        payload = MagicMock()
        payload.data = {"created": True, "verification_id": record_id}
        chain.execute.return_value = payload
        return chain

    mock_sb.rpc.side_effect = capture_rpc

    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.email.send_login_otp_email",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.auth.email_otp.generate_email_otp_code",
            return_value="111111",
        ),
    ):
        asyncio.run(create_and_send_email_otp(email="  Student@Example.COM "))

    assert rpc_params["params"]["p_email"] == "student@example.com"


def test_create_and_send_email_otp_rejects_missing_resend_in_production():
    mock_sb = _mock_rpc()
    settings = _settings(
        app_env="production",
        resend_api_key="",
        auth_demo_otp_enabled=False,
    )
    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
    ):
        with pytest.raises(OtpError) as exc:
            asyncio.run(create_and_send_email_otp(email=EMAIL))
    assert exc.value.status_code == 503
    assert "Resend" in exc.value.message
    mock_sb.rpc.assert_not_called()


def test_create_and_send_email_otp_enforces_resend_cooldown():
    mock_sb = _mock_rpc(
        create_data={"created": False, "cooldown": True, "wait_seconds": 51},
    )
    settings = _settings()
    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.email.send_login_otp_email",
            new_callable=AsyncMock,
            return_value=True,
        ) as send_email,
    ):
        with pytest.raises(OtpError) as exc:
            asyncio.run(create_and_send_email_otp(email=EMAIL))
    assert exc.value.status_code == 429
    assert "wait" in exc.value.message.lower()
    assert OTP_RESEND_COOLDOWN_SECONDS >= 60
    send_email.assert_not_awaited()


def test_create_and_send_email_otp_cooldown_rpc_response_does_not_send_email():
    mock_sb = _mock_rpc(
        create_data={"created": False, "cooldown": True, "wait_seconds": 42},
    )
    settings = _settings()
    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.email.send_login_otp_email",
            new_callable=AsyncMock,
            return_value=True,
        ) as send_email,
    ):
        with pytest.raises(OtpError) as exc:
            asyncio.run(create_and_send_email_otp(email=EMAIL))
    assert exc.value.status_code == 429
    assert "42" in exc.value.message
    send_email.assert_not_awaited()
    mock_sb.table.assert_not_called()


def test_create_and_send_email_otp_demo_hint():
    record_id = str(uuid4())
    mock_sb = _mock_rpc(
        create_data={"created": True, "verification_id": record_id},
    )
    settings = _settings(auth_demo_otp="123456")
    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.email.send_login_otp_email",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        hint = asyncio.run(create_and_send_email_otp(email=EMAIL))
    assert hint is not None
    assert "Demo mode" in hint


def test_create_and_send_email_otp_invalidates_record_when_delivery_fails():
    record_id = str(uuid4())
    mock_sb = _mock_rpc(
        create_data={"created": True, "verification_id": record_id},
    )
    invalidate_result = MagicMock()
    invalidate_result.data = [{"id": record_id}]
    mock_sb.table.return_value.execute.return_value = invalidate_result
    settings = _settings(
        app_env="production",
        auth_demo_otp_enabled=False,
        resend_api_key="re_live",
    )
    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.email.send_login_otp_email",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        with pytest.raises(OtpError) as exc:
            asyncio.run(create_and_send_email_otp(email=EMAIL))
    assert exc.value.status_code == 503
    assert exc.value.message == "Could not send OTP. Try again later."
    mock_sb.table.return_value.update.assert_called_once()


def test_create_and_send_email_otp_invalidates_record_when_sender_raises():
    record_id = str(uuid4())
    mock_sb = _mock_rpc(
        create_data={"created": True, "verification_id": record_id},
    )
    invalidate_result = MagicMock()
    invalidate_result.data = [{"id": record_id}]
    mock_sb.table.return_value.execute.return_value = invalidate_result
    settings = _settings(
        app_env="production",
        auth_demo_otp_enabled=False,
        resend_api_key="re_live",
    )
    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.email.send_login_otp_email",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Resend unavailable"),
        ),
    ):
        with pytest.raises(OtpError) as exc:
            asyncio.run(create_and_send_email_otp(email=EMAIL))
    assert exc.value.status_code == 503
    assert exc.value.message == "Could not send OTP. Try again later."
    assert "Resend unavailable" not in exc.value.message
    mock_sb.table.return_value.update.assert_called_once()


def test_verify_email_otp_code_success_marks_consumed_with_expiry_guard():
    now = utcnow()
    record_id = str(uuid4())
    mock_sb, select_result = _supabase_chain(
        [
            {
                "id": record_id,
                "attempts": 0,
                "max_attempts": 5,
                "expires_at": (now + timedelta(minutes=5)).isoformat(),
                "code_hash": hash_otp("654321"),
            }
        ]
    )
    consume_result = MagicMock()
    consume_result.data = [{"id": record_id}]
    table = mock_sb.table.return_value
    table.execute.side_effect = [select_result, consume_result]

    settings = _settings(auth_demo_otp="", auth_open_otp=False)
    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
    ):
        asyncio.run(
            verify_email_otp_code(
                email="  Student@Example.COM ",
                code="654321",
                purpose=OTP_PURPOSE_LOGIN,
            )
        )

    table.gt.assert_called_once()
    assert table.gt.call_args.args[0] == "expires_at"
    table.is_.assert_any_call("consumed_at", "null")


def test_verify_email_otp_code_rejects_consume_after_expiry_at_final_update():
    now = utcnow()
    record_id = str(uuid4())
    mock_sb, select_result = _supabase_chain(
        [
            {
                "id": record_id,
                "attempts": 0,
                "max_attempts": 5,
                "expires_at": (now + timedelta(minutes=5)).isoformat(),
                "code_hash": hash_otp("654321"),
            }
        ]
    )
    consume_result = MagicMock()
    consume_result.data = []
    table = mock_sb.table.return_value
    table.execute.side_effect = [select_result, consume_result]

    settings = _settings(auth_demo_otp="", auth_open_otp=False)
    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
    ):
        with pytest.raises(OtpError) as exc:
            asyncio.run(
                verify_email_otp_code(
                    email=EMAIL,
                    code="654321",
                    purpose=OTP_PURPOSE_LOGIN,
                )
            )
    assert exc.value.status_code == 401
    assert "expired or not found" in exc.value.message.lower()
    table.gt.assert_called_once()


def test_verify_email_otp_code_rejects_reuse_after_consumption():
    mock_sb, result = _supabase_chain([])
    settings = _settings(auth_demo_otp="", auth_open_otp=False)
    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
    ):
        with pytest.raises(OtpError) as exc:
            asyncio.run(
                verify_email_otp_code(
                    email=EMAIL,
                    code="654321",
                    purpose=OTP_PURPOSE_LOGIN,
                )
            )
    assert exc.value.status_code == 401
    assert "expired or not found" in exc.value.message.lower()


def test_verify_email_otp_code_uses_rpc_for_wrong_code_attempt_increment():
    now = utcnow()
    record_id = str(uuid4())
    mock_sb = _mock_rpc(
        increment_data={
            "found": True,
            "incremented": True,
            "attempts": 2,
            "max_attempts": 5,
        },
    )
    select_result = MagicMock()
    select_result.data = [
        {
            "id": record_id,
            "attempts": 1,
            "max_attempts": 5,
            "expires_at": (now + timedelta(minutes=5)).isoformat(),
            "code_hash": hash_otp("654321"),
        }
    ]
    mock_sb.table.return_value.execute.return_value = select_result

    settings = _settings(auth_demo_otp="", auth_open_otp=False)
    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
    ):
        with pytest.raises(OtpError) as exc:
            asyncio.run(
                verify_email_otp_code(
                    email=EMAIL,
                    code="000000",
                    purpose=OTP_PURPOSE_LOGIN,
                )
            )
    assert exc.value.status_code == 401
    assert "Invalid" in exc.value.message
    mock_sb.rpc.assert_called_with(
        "increment_email_otp_attempt",
        {"p_verification_id": record_id},
    )


def test_verify_email_otp_code_rpc_at_limit_returns_429_on_concurrent_loss():
    now = utcnow()
    record_id = str(uuid4())
    mock_sb = _mock_rpc(
        increment_data={
            "found": True,
            "incremented": False,
            "attempts": 5,
            "max_attempts": 5,
        },
    )
    select_result = MagicMock()
    select_result.data = [
        {
            "id": record_id,
            "attempts": 4,
            "max_attempts": 5,
            "expires_at": (now + timedelta(minutes=5)).isoformat(),
            "code_hash": hash_otp("654321"),
        }
    ]
    mock_sb.table.return_value.execute.return_value = select_result

    settings = _settings(auth_demo_otp="", auth_open_otp=False)
    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
    ):
        with pytest.raises(OtpError) as exc:
            asyncio.run(
                verify_email_otp_code(
                    email=EMAIL,
                    code="000000",
                    purpose=OTP_PURPOSE_LOGIN,
                )
            )
    assert exc.value.status_code == 429
    assert "Too many attempts" in exc.value.message


def test_verify_email_otp_code_rejects_when_attempt_limit_reached():
    now = utcnow()
    mock_sb, result = _supabase_chain(
        [
            {
                "id": str(uuid4()),
                "attempts": 5,
                "max_attempts": 5,
                "expires_at": (now + timedelta(minutes=5)).isoformat(),
                "code_hash": hash_otp("654321"),
            }
        ]
    )
    settings = _settings(auth_demo_otp="", auth_open_otp=False)
    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
    ):
        with pytest.raises(OtpError) as exc:
            asyncio.run(
                verify_email_otp_code(
                    email=EMAIL,
                    code="654321",
                    purpose=OTP_PURPOSE_LOGIN,
                )
            )
    assert exc.value.status_code == 429
    assert "Too many attempts" in exc.value.message


def test_verify_email_otp_code_rejects_expired():
    now = utcnow()
    mock_sb, result = _supabase_chain(
        [
            {
                "id": str(uuid4()),
                "attempts": 0,
                "max_attempts": 5,
                "expires_at": (now - timedelta(minutes=1)).isoformat(),
                "code_hash": hash_otp("654321"),
            }
        ]
    )
    settings = _settings(auth_demo_otp="", auth_open_otp=False)
    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
    ):
        with pytest.raises(OtpError) as exc:
            asyncio.run(
                verify_email_otp_code(
                    email=EMAIL,
                    code="654321",
                    purpose=OTP_PURPOSE_LOGIN,
                )
            )
    assert exc.value.status_code == 401
    assert "expired" in exc.value.message.lower()


def test_verify_email_otp_code_accepts_demo_otp_in_demo_mode():
    now = utcnow()
    record_id = str(uuid4())
    mock_sb, select_result = _supabase_chain([{"id": record_id}])
    consume_result = MagicMock()
    consume_result.data = [{"id": record_id}]
    table = mock_sb.table.return_value
    table.execute.side_effect = [select_result, consume_result]
    settings = _settings(auth_demo_otp="123456")
    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
    ):
        asyncio.run(
            verify_email_otp_code(
                email=EMAIL,
                code="123456",
                purpose=OTP_PURPOSE_LOGIN,
            )
        )


def test_verify_email_otp_code_rejects_demo_code_in_production_without_demo_flag():
    now = utcnow()
    mock_sb, result = _supabase_chain(
        [
            {
                "id": str(uuid4()),
                "attempts": 0,
                "max_attempts": 5,
                "expires_at": (now + timedelta(minutes=5)).isoformat(),
                "code_hash": hash_otp("999999"),
            }
        ]
    )
    settings = _settings(
        app_env="production",
        auth_demo_otp="123456",
        auth_demo_otp_enabled=False,
        auth_open_otp=False,
    )
    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
    ):
        with pytest.raises(OtpError) as exc:
            asyncio.run(
                verify_email_otp_code(
                    email=EMAIL,
                    code="123456",
                    purpose=OTP_PURPOSE_LOGIN,
                )
            )
    assert exc.value.status_code == 401
    assert "Invalid" in exc.value.message


def test_verify_email_otp_code_rejects_open_otp_in_production_without_demo_flag():
    settings = _settings(
        app_env="production",
        auth_demo_otp_enabled=False,
        auth_open_otp=True,
    )
    mock_sb, result = _supabase_chain([])
    with (
        patch("app.auth.email_otp.get_settings", return_value=settings),
        patch("app.auth.email_otp.get_supabase", return_value=mock_sb),
    ):
        with pytest.raises(OtpError) as exc:
            asyncio.run(
                verify_email_otp_code(
                    email=EMAIL,
                    code="000000",
                    purpose=OTP_PURPOSE_LOGIN,
                )
            )
    assert exc.value.status_code == 401
