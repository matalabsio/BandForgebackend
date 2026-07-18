"""Shared Redis-backed rate limits (in-process fallback).

Used by Phase 5 Core Security (S6 / 5f):
- POST /auth/login — per IP
- POST /api/payments/create-order — per user
- POST /api/payments/verify — per user
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request, status

# Defaults documented in Razorpay.md §5f.
LOGIN_LIMIT = 10
LOGIN_WINDOW_SEC = 60
CREATE_ORDER_LIMIT = 10
CREATE_ORDER_WINDOW_SEC = 60
VERIFY_LIMIT = 30
VERIFY_WINDOW_SEC = 60

_buckets: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _prune(timestamps: list[float], now: float, window_sec: int) -> list[float]:
    return [t for t in timestamps if now - t < window_sec]


def _memory_allow(key: str, *, limit: int, window_sec: int) -> bool:
    """Return True if the request is allowed (and record it)."""
    now = time.time()
    with _lock:
        recent = _prune(_buckets[key], now, window_sec)
        if len(recent) >= limit:
            _buckets[key] = recent
            return False
        recent.append(now)
        _buckets[key] = recent
        return True


def _redis_allow(key: str, *, limit: int, window_sec: int) -> bool | None:
    """
    Return True/False when Redis works; None to fall back to memory.
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


def enforce_rate_limit(
    *,
    bucket: str,
    identity: str,
    limit: int,
    window_sec: int,
    detail: str,
) -> None:
    """Raise HTTP 429 when ``identity`` exceeds ``limit`` in ``window_sec``."""
    key = f"{bucket}:{identity}"
    allowed = _redis_allow(key, limit=limit, window_sec=window_sec)
    if allowed is None:
        allowed = _memory_allow(key, limit=limit, window_sec=window_sec)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
        )


def reset_rate_limit_state_for_tests() -> None:
    """Clear in-process buckets (unit tests only)."""
    with _lock:
        _buckets.clear()


def enforce_login_rate_limit(request: Request) -> None:
    enforce_rate_limit(
        bucket="auth:login",
        identity=client_ip(request),
        limit=LOGIN_LIMIT,
        window_sec=LOGIN_WINDOW_SEC,
        detail="Too many login attempts. Please try again shortly.",
    )


def enforce_create_order_rate_limit(*, user_id: str) -> None:
    enforce_rate_limit(
        bucket="payments:create-order",
        identity=user_id,
        limit=CREATE_ORDER_LIMIT,
        window_sec=CREATE_ORDER_WINDOW_SEC,
        detail="Too many order attempts. Please try again shortly.",
    )


def enforce_verify_rate_limit(*, user_id: str) -> None:
    enforce_rate_limit(
        bucket="payments:verify",
        identity=user_id,
        limit=VERIFY_LIMIT,
        window_sec=VERIFY_WINDOW_SEC,
        detail="Too many verify attempts. Please try again shortly.",
    )
