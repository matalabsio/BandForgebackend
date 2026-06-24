"""Rate limiting for diagnostic evaluate-writing (3 per IP per hour)."""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request, status

_LIMIT = 3
_WINDOW_SEC = 3600

# In-process fallback when Redis is unavailable (dev / single worker).
_buckets: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _prune(timestamps: list[float], now: float) -> list[float]:
    return [t for t in timestamps if now - t < _WINDOW_SEC]


def check_evaluate_writing_rate_limit(request: Request) -> None:
    """Raise 429 if IP exceeded 3 evaluations in the last hour."""
    ip = _client_ip(request)
    now = time.time()

    with _lock:
        recent = _prune(_buckets[ip], now)
        if len(recent) >= _LIMIT:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many writing evaluations. Please try again in an hour.",
            )
        recent.append(now)
        _buckets[ip] = recent


def record_evaluate_writing_rate_limit(request: Request) -> None:
    """Count a Groq evaluation against the IP limit (not used on cache hits)."""
    check_evaluate_writing_rate_limit(request)
