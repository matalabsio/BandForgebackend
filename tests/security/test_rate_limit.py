"""Unit tests for shared Phase 5 rate limits."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.security import rate_limit as rl


@pytest.fixture(autouse=True)
def _clear_buckets():
    rl.reset_rate_limit_state_for_tests()
    yield
    rl.reset_rate_limit_state_for_tests()


def _request(ip: str = "203.0.113.10") -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/auth/login",
        "raw_path": b"/auth/login",
        "query_string": b"",
        "headers": [],
        "client": (ip, 12345),
        "server": ("test", 80),
    }
    return Request(scope)


def test_memory_allows_up_to_limit_then_429():
    with (
        patch("app.security.rate_limit._redis_allow", return_value=None),
        patch("app.security.rate_limit.rate_limit_fail_closed", return_value=False),
    ):
        for _ in range(rl.LOGIN_LIMIT):
            rl.enforce_rate_limit(
                bucket="auth:login",
                identity="1.2.3.4",
                limit=rl.LOGIN_LIMIT,
                window_sec=rl.LOGIN_WINDOW_SEC,
                detail="too many",
            )
        with pytest.raises(HTTPException) as exc:
            rl.enforce_rate_limit(
                bucket="auth:login",
                identity="1.2.3.4",
                limit=rl.LOGIN_LIMIT,
                window_sec=rl.LOGIN_WINDOW_SEC,
                detail="too many",
            )
    assert exc.value.status_code == 429
    assert exc.value.detail == "too many"


def test_identities_are_isolated():
    with (
        patch("app.security.rate_limit._redis_allow", return_value=None),
        patch("app.security.rate_limit.rate_limit_fail_closed", return_value=False),
    ):
        for _ in range(rl.LOGIN_LIMIT):
            rl.enforce_rate_limit(
                bucket="auth:login",
                identity="a",
                limit=rl.LOGIN_LIMIT,
                window_sec=60,
                detail="too many",
            )
        # Different identity still allowed.
        rl.enforce_rate_limit(
            bucket="auth:login",
            identity="b",
            limit=rl.LOGIN_LIMIT,
            window_sec=60,
            detail="too many",
        )


def test_login_helper_uses_client_ip():
    req = _request("198.51.100.7")
    with (
        patch("app.security.rate_limit._redis_allow", return_value=None),
        patch("app.security.rate_limit.rate_limit_fail_closed", return_value=False),
    ):
        for _ in range(rl.LOGIN_LIMIT):
            rl.enforce_login_rate_limit(req)
        with pytest.raises(HTTPException) as exc:
            rl.enforce_login_rate_limit(req)
    assert exc.value.status_code == 429


def test_send_otp_helper_per_phone():
    from app.auth.constants import OTP_RATE_LIMIT_PER_PHONE

    with (
        patch("app.security.rate_limit._redis_allow", return_value=None),
        patch("app.security.rate_limit.rate_limit_fail_closed", return_value=False),
    ):
        for _ in range(OTP_RATE_LIMIT_PER_PHONE):
            rl.enforce_send_otp_rate_limit(phone="9876543210")
        with pytest.raises(HTTPException) as exc:
            rl.enforce_send_otp_rate_limit(phone="9876543210")
    assert exc.value.status_code == 429
    with (
        patch("app.security.rate_limit._redis_allow", return_value=None),
        patch("app.security.rate_limit.rate_limit_fail_closed", return_value=False),
    ):
        rl.enforce_send_otp_rate_limit(phone="9123456789")


def test_create_order_and_verify_helpers():
    with (
        patch("app.security.rate_limit._redis_allow", return_value=None),
        patch("app.security.rate_limit.rate_limit_fail_closed", return_value=False),
    ):
        for _ in range(rl.CREATE_ORDER_LIMIT):
            rl.enforce_create_order_rate_limit(user_id="user-1")
        with pytest.raises(HTTPException) as exc:
            rl.enforce_create_order_rate_limit(user_id="user-1")
        assert exc.value.status_code == 429

        for _ in range(rl.VERIFY_LIMIT):
            rl.enforce_verify_rate_limit(user_id="user-1")
        with pytest.raises(HTTPException) as exc2:
            rl.enforce_verify_rate_limit(user_id="user-1")
        assert exc2.value.status_code == 429


def test_redis_path_increments_and_blocks():
    fake = MagicMock()
    # First LOGIN_LIMIT calls return 1..LIMIT; next returns LIMIT+1.
    fake.incr.side_effect = list(range(1, rl.LOGIN_LIMIT + 2))
    with patch("app.cache.hybrid_cache._get_redis", return_value=fake):
        for _ in range(rl.LOGIN_LIMIT):
            rl.enforce_rate_limit(
                bucket="auth:login",
                identity="ip",
                limit=rl.LOGIN_LIMIT,
                window_sec=60,
                detail="too many",
            )
        with pytest.raises(HTTPException) as exc:
            rl.enforce_rate_limit(
                bucket="auth:login",
                identity="ip",
                limit=rl.LOGIN_LIMIT,
                window_sec=60,
                detail="too many",
            )
    assert exc.value.status_code == 429
    assert fake.expire.called


def test_redis_unavailable_fail_closed_returns_503():
    with (
        patch("app.security.rate_limit._redis_allow", return_value=None),
        patch("app.security.rate_limit.rate_limit_fail_closed", return_value=True),
    ):
        with pytest.raises(HTTPException) as exc:
            rl.enforce_rate_limit(
                bucket="auth:login",
                identity="ip",
                limit=1,
                window_sec=60,
                detail="too many",
            )
    assert exc.value.status_code == 503
    assert "unavailable" in str(exc.value.detail).lower()


def test_redis_unavailable_non_prod_uses_memory():
    with (
        patch("app.security.rate_limit._redis_allow", return_value=None),
        patch("app.security.rate_limit.rate_limit_fail_closed", return_value=False),
    ):
        rl.enforce_rate_limit(
            bucket="auth:login",
            identity="ip-memory",
            limit=2,
            window_sec=60,
            detail="too many",
        )
        rl.enforce_rate_limit(
            bucket="auth:login",
            identity="ip-memory",
            limit=2,
            window_sec=60,
            detail="too many",
        )
        with pytest.raises(HTTPException) as exc:
            rl.enforce_rate_limit(
                bucket="auth:login",
                identity="ip-memory",
                limit=2,
                window_sec=60,
                detail="too many",
            )
    assert exc.value.status_code == 429


def test_ai_and_public_helpers_exceed_to_429():
    req = _request("198.51.100.9")
    with (
        patch("app.security.rate_limit._redis_allow", return_value=None),
        patch("app.security.rate_limit.rate_limit_fail_closed", return_value=False),
    ):
        for _ in range(rl.AI_TUTOR_CHAT_LIMIT):
            rl.enforce_tutor_chat_rate_limit(user_id="u1")
        with pytest.raises(HTTPException) as exc:
            rl.enforce_tutor_chat_rate_limit(user_id="u1")
        assert exc.value.status_code == 429

        for _ in range(rl.GUEST_SESSION_LIMIT):
            rl.enforce_guest_session_rate_limit(req)
        with pytest.raises(HTTPException) as exc2:
            rl.enforce_guest_session_rate_limit(req)
        assert exc2.value.status_code == 429

        for _ in range(rl.AI_WRITING_SUBMIT_LIMIT):
            rl.enforce_writing_submit_rate_limit(user_id="u2")
        with pytest.raises(HTTPException) as exc3:
            rl.enforce_writing_submit_rate_limit(user_id="u2")
        assert exc3.value.status_code == 429
