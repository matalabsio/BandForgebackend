"""Shared Redis-backed rate limits with production fail-closed behavior.

Used by:
- POST /auth/login — per IP
- POST /auth/send-otp — per phone and per IP
- POST /auth/send-email-otp — per IP and per email
- POST /auth/verify-otp — per IP (login bucket)
- POST /auth/register, /forgot-password, /collect-lead — per IP
- POST /api/payments/create-order|verify — per user
- POST /api/diagnostic/* public abuse surfaces — per IP
- AI spend paths (writing/speaking submit, tutor chat) — per user
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request, status

# Defaults (overridable via env / Settings).
LOGIN_LIMIT = 10
LOGIN_WINDOW_SEC = 60
CREATE_ORDER_LIMIT = 10
CREATE_ORDER_WINDOW_SEC = 60
VERIFY_LIMIT = 30
VERIFY_WINDOW_SEC = 60

REGISTER_LIMIT = 5
REGISTER_WINDOW_SEC = 900
FORGOT_PASSWORD_LIMIT = 5
FORGOT_PASSWORD_WINDOW_SEC = 900
COLLECT_LEAD_LIMIT = 10
COLLECT_LEAD_WINDOW_SEC = 3600

GUEST_SESSION_LIMIT = 20
GUEST_SESSION_WINDOW_SEC = 3600
SUBMIT_REVIEW_LIMIT = 10
SUBMIT_REVIEW_WINDOW_SEC = 3600
EVALUATE_WRITING_LIMIT = 3
EVALUATE_WRITING_WINDOW_SEC = 3600

AI_WRITING_SUBMIT_LIMIT = 10
AI_WRITING_SUBMIT_WINDOW_SEC = 3600
AI_SPEAKING_SUBMIT_LIMIT = 10
AI_SPEAKING_SUBMIT_WINDOW_SEC = 3600
AI_TUTOR_CHAT_LIMIT = 30
AI_TUTOR_CHAT_WINDOW_SEC = 3600

RATE_LIMITER_UNAVAILABLE_DETAIL = (
    "Rate limiter temporarily unavailable. Please try again shortly."
)

_buckets: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def client_ip(request: Request) -> str:
    """Identify the client for rate limits.

    Default: ``request.client.host`` (safe behind Railway/trusted proxies).
    When ``TRUST_X_FORWARDED_FOR`` is enabled, use the **rightmost** XFF hop
    (never the leftmost client-supplied value).
    """
    from app.config import get_settings

    settings = get_settings()
    if settings.trust_x_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            hops = [h.strip() for h in forwarded.split(",") if h.strip()]
            if hops:
                return hops[-1]
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


_MAX_BUCKET_KEYS = 10_000
_PRUNE_EVERY_N = 64
_write_count = 0


def _prune(timestamps: list[float], now: float, window_sec: int) -> list[float]:
    return [t for t in timestamps if now - t < window_sec]


def _prune_all_buckets(now: float) -> None:
    """Drop expired timestamps and empty keys across the map."""
    stale: list[str] = []
    for key, stamps in _buckets.items():
        recent = _prune(
            stamps,
            now,
            max(
                LOGIN_WINDOW_SEC,
                CREATE_ORDER_WINDOW_SEC,
                VERIFY_WINDOW_SEC,
                COLLECT_LEAD_WINDOW_SEC,
                AI_TUTOR_CHAT_WINDOW_SEC,
            ),
        )
        if recent:
            _buckets[key] = recent
        else:
            stale.append(key)
    for key in stale:
        _buckets.pop(key, None)
    while len(_buckets) > _MAX_BUCKET_KEYS:
        _buckets.pop(next(iter(_buckets)))


def _memory_allow(key: str, *, limit: int, window_sec: int) -> bool:
    """Return True if the request is allowed (and record it)."""
    global _write_count
    now = time.time()
    with _lock:
        _write_count += 1
        if _write_count % _PRUNE_EVERY_N == 0 or len(_buckets) > _MAX_BUCKET_KEYS:
            _prune_all_buckets(now)
        recent = _prune(_buckets[key], now, window_sec)
        if len(recent) >= limit:
            _buckets[key] = recent
            return False
        recent.append(now)
        _buckets[key] = recent
        return True


def _redis_allow(key: str, *, limit: int, window_sec: int) -> bool | None:
    """
    Return True/False when Redis works; None to fall back / fail-closed.
    Counts the current request via INCR.
    """
    try:
        from app.cache.hybrid_cache import _get_redis
    except Exception:
        return None
    client = _get_redis()
    if not client:
        return None
    redis_key = f"rl:{key}"
    try:
        count = int(client.incr(redis_key))
        if count == 1:
            client.expire(redis_key, window_sec)
        return count <= limit
    except Exception:
        return None


def rate_limit_fail_closed() -> bool:
    """Production + REDIS_URL → fail closed unless RATE_LIMIT_FAIL_CLOSED overrides."""
    from app.config import get_settings

    settings = get_settings()
    if settings.rate_limit_fail_closed is not None:
        return bool(settings.rate_limit_fail_closed)
    return (
        settings.app_env.strip().lower() == "production"
        and bool(settings.redis_url.strip())
    )


def enforce_rate_limit(
    *,
    bucket: str,
    identity: str,
    limit: int,
    window_sec: int,
    detail: str,
) -> None:
    """Raise HTTP 429 when ``identity`` exceeds ``limit`` in ``window_sec``.

    When Redis is unavailable and fail-closed is active, raises HTTP 503
    (rate limiter unavailable) instead of falling back to in-process memory.
    """
    key = f"{bucket}:{identity}"
    allowed = _redis_allow(key, limit=limit, window_sec=window_sec)
    if allowed is None:
        if rate_limit_fail_closed():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=RATE_LIMITER_UNAVAILABLE_DETAIL,
            )
        allowed = _memory_allow(key, limit=limit, window_sec=window_sec)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
        )


def enforce_ip_rate_limit(
    request: Request,
    *,
    bucket: str,
    limit: int,
    window_sec: int,
    detail: str,
) -> None:
    enforce_rate_limit(
        bucket=bucket,
        identity=client_ip(request),
        limit=limit,
        window_sec=window_sec,
        detail=detail,
    )


def enforce_user_rate_limit(
    *,
    user_id: str,
    bucket: str,
    limit: int,
    window_sec: int,
    detail: str,
) -> None:
    enforce_rate_limit(
        bucket=bucket,
        identity=str(user_id),
        limit=limit,
        window_sec=window_sec,
        detail=detail,
    )


def reset_rate_limit_state_for_tests() -> None:
    """Clear in-process buckets (unit tests only)."""
    with _lock:
        _buckets.clear()


def _limit(settings_attr: str, default: int) -> int:
    from app.config import get_settings

    settings = get_settings()
    value = getattr(settings, settings_attr, None)
    if value is None:
        return default
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def enforce_login_rate_limit(request: Request) -> None:
    enforce_ip_rate_limit(
        request,
        bucket="auth:login",
        limit=_limit("rate_limit_login", LOGIN_LIMIT),
        window_sec=LOGIN_WINDOW_SEC,
        detail="Too many login attempts. Please try again shortly.",
    )


def enforce_send_otp_ip_rate_limit(request: Request) -> None:
    from app.auth.constants import (
        OTP_RATE_LIMIT_PER_PHONE,
        OTP_RATE_LIMIT_WINDOW_SECONDS,
    )

    enforce_ip_rate_limit(
        request,
        bucket="auth:send-otp-ip",
        limit=OTP_RATE_LIMIT_PER_PHONE,
        window_sec=OTP_RATE_LIMIT_WINDOW_SECONDS,
        detail="Too many OTP requests from this address. Please try again later.",
    )


def enforce_send_otp_rate_limit(*, phone: str) -> None:
    from app.auth.constants import (
        OTP_RATE_LIMIT_PER_PHONE,
        OTP_RATE_LIMIT_WINDOW_SECONDS,
    )

    enforce_rate_limit(
        bucket="auth:send-otp",
        identity=phone,
        limit=OTP_RATE_LIMIT_PER_PHONE,
        window_sec=OTP_RATE_LIMIT_WINDOW_SECONDS,
        detail="Too many OTP requests for this number. Please try again later.",
    )


def enforce_send_email_otp_ip_rate_limit(request: Request) -> None:
    from app.auth.constants import (
        OTP_RATE_LIMIT_PER_PHONE,
        OTP_RATE_LIMIT_WINDOW_SECONDS,
    )

    enforce_ip_rate_limit(
        request,
        bucket="auth:send-email-otp-ip",
        limit=OTP_RATE_LIMIT_PER_PHONE,
        window_sec=OTP_RATE_LIMIT_WINDOW_SECONDS,
        detail="Too many OTP requests from this address. Please try again later.",
    )


def enforce_send_email_otp_rate_limit(*, email: str) -> None:
    from app.auth.constants import (
        OTP_RATE_LIMIT_PER_PHONE,
        OTP_RATE_LIMIT_WINDOW_SECONDS,
    )

    enforce_rate_limit(
        bucket="auth:send-email-otp",
        identity=email,
        limit=OTP_RATE_LIMIT_PER_PHONE,
        window_sec=OTP_RATE_LIMIT_WINDOW_SECONDS,
        detail="Too many OTP requests for this email. Please try again later.",
    )


def enforce_create_order_rate_limit(*, user_id: str) -> None:
    enforce_user_rate_limit(
        user_id=user_id,
        bucket="payments:create-order",
        limit=_limit("rate_limit_create_order", CREATE_ORDER_LIMIT),
        window_sec=CREATE_ORDER_WINDOW_SEC,
        detail="Too many order attempts. Please try again shortly.",
    )


def enforce_verify_rate_limit(*, user_id: str) -> None:
    enforce_user_rate_limit(
        user_id=user_id,
        bucket="payments:verify",
        limit=_limit("rate_limit_verify", VERIFY_LIMIT),
        window_sec=VERIFY_WINDOW_SEC,
        detail="Too many verify attempts. Please try again shortly.",
    )


def enforce_register_rate_limit(request: Request) -> None:
    enforce_ip_rate_limit(
        request,
        bucket="auth:register",
        limit=_limit("rate_limit_register", REGISTER_LIMIT),
        window_sec=REGISTER_WINDOW_SEC,
        detail="Too many registration attempts. Please try again later.",
    )


def enforce_forgot_password_rate_limit(request: Request) -> None:
    enforce_ip_rate_limit(
        request,
        bucket="auth:forgot-password",
        limit=_limit("rate_limit_forgot_password", FORGOT_PASSWORD_LIMIT),
        window_sec=FORGOT_PASSWORD_WINDOW_SEC,
        detail="Too many password reset attempts. Please try again later.",
    )


def enforce_collect_lead_rate_limit(request: Request) -> None:
    enforce_ip_rate_limit(
        request,
        bucket="auth:collect-lead",
        limit=_limit("rate_limit_collect_lead", COLLECT_LEAD_LIMIT),
        window_sec=COLLECT_LEAD_WINDOW_SEC,
        detail="Too many lead submissions. Please try again later.",
    )


def enforce_guest_session_rate_limit(request: Request) -> None:
    enforce_ip_rate_limit(
        request,
        bucket="diagnostic:guest-session",
        limit=_limit("rate_limit_guest_session", GUEST_SESSION_LIMIT),
        window_sec=GUEST_SESSION_WINDOW_SEC,
        detail="Too many guest sessions. Please try again later.",
    )


def enforce_submit_review_rate_limit(request: Request) -> None:
    enforce_ip_rate_limit(
        request,
        bucket="diagnostic:submit-review",
        limit=_limit("rate_limit_submit_review", SUBMIT_REVIEW_LIMIT),
        window_sec=SUBMIT_REVIEW_WINDOW_SEC,
        detail="Too many review submissions. Please try again later.",
    )


def enforce_evaluate_writing_rate_limit(request: Request) -> None:
    enforce_ip_rate_limit(
        request,
        bucket="diagnostic:evaluate-writing",
        limit=_limit("rate_limit_evaluate_writing", EVALUATE_WRITING_LIMIT),
        window_sec=EVALUATE_WRITING_WINDOW_SEC,
        detail="Too many writing evaluations. Please try again in an hour.",
    )


def enforce_writing_submit_rate_limit(*, user_id: str) -> None:
    enforce_user_rate_limit(
        user_id=user_id,
        bucket="ai:writing-submit",
        limit=_limit("rate_limit_ai_writing_submit", AI_WRITING_SUBMIT_LIMIT),
        window_sec=AI_WRITING_SUBMIT_WINDOW_SEC,
        detail="Too many writing submissions. Please try again later.",
    )


def enforce_speaking_submit_rate_limit(*, user_id: str) -> None:
    enforce_user_rate_limit(
        user_id=user_id,
        bucket="ai:speaking-submit",
        limit=_limit("rate_limit_ai_speaking_submit", AI_SPEAKING_SUBMIT_LIMIT),
        window_sec=AI_SPEAKING_SUBMIT_WINDOW_SEC,
        detail="Too many speaking submissions. Please try again later.",
    )


def enforce_tutor_chat_rate_limit(*, user_id: str) -> None:
    enforce_user_rate_limit(
        user_id=user_id,
        bucket="ai:tutor-chat",
        limit=_limit("rate_limit_ai_tutor_chat", AI_TUTOR_CHAT_LIMIT),
        window_sec=AI_TUTOR_CHAT_WINDOW_SEC,
        detail="Too many tutor messages. Please try again later.",
    )
