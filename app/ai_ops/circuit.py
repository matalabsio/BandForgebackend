"""Simple circuit breaker for Claude writing evaluations."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Lock

from app.config import get_settings

logger = logging.getLogger(__name__)

_PREFIX = "bf:ai:circuit:claude"
_lock = Lock()
_mem_failures: list[float] = []
_mem_open_until: float = 0.0


def _get_redis():
    from app.cache.hybrid_cache import _get_redis as get_redis_client

    return get_redis_client()


@dataclass(frozen=True)
class CircuitStatus:
    open: bool
    failures: int
    open_until: float | None
    reason: str | None = None


def _prune(timestamps: list[float], *, window_sec: float, now: float) -> list[float]:
    return [t for t in timestamps if now - t <= window_sec]


def is_claude_circuit_open() -> CircuitStatus:
    settings = get_settings()
    cooldown = max(1, int(settings.ai_circuit_cooldown_sec))
    threshold = max(1, int(settings.ai_circuit_fail_threshold))
    now = time.time()
    client = _get_redis()

    if client is not None:
        try:
            open_key = f"{_PREFIX}:open_until"
            fail_key = f"{_PREFIX}:fails"
            pipe = client.pipeline(transaction=False)
            pipe.get(open_key)
            pipe.zremrangebyscore(fail_key, 0, now - cooldown)
            pipe.zcard(fail_key)
            open_until_raw, _removed, failures_raw = pipe.execute()
            if open_until_raw is not None:
                open_until = float(open_until_raw)
                if open_until > now:
                    return CircuitStatus(
                        open=True,
                        failures=threshold,
                        open_until=open_until,
                        reason="circuit_open",
                    )
            failures = int(failures_raw or 0)
            return CircuitStatus(
                open=False,
                failures=failures,
                open_until=None,
            )
        except Exception:
            logger.debug("Redis circuit read failed", exc_info=True)

    global _mem_open_until
    with _lock:
        if _mem_open_until > now:
            return CircuitStatus(
                open=True,
                failures=threshold,
                open_until=_mem_open_until,
                reason="circuit_open",
            )
        recent = _prune(_mem_failures, window_sec=float(cooldown), now=now)
        _mem_failures[:] = recent
        return CircuitStatus(open=False, failures=len(recent), open_until=None)


def record_claude_failure() -> CircuitStatus:
    settings = get_settings()
    cooldown = max(1, int(settings.ai_circuit_cooldown_sec))
    threshold = max(1, int(settings.ai_circuit_fail_threshold))
    now = time.time()
    client = _get_redis()

    if client is not None:
        try:
            fail_key = f"{_PREFIX}:fails"
            member = f"{now}:{id(object())}"
            client.zadd(fail_key, {member: now})
            client.zremrangebyscore(fail_key, 0, now - cooldown)
            client.expire(fail_key, cooldown * 2)
            failures = int(client.zcard(fail_key) or 0)
            if failures >= threshold:
                open_until = now + cooldown
                client.setex(f"{_PREFIX}:open_until", cooldown, str(open_until))
                logger.warning(
                    "Claude circuit OPEN for %ss after %s failures",
                    cooldown,
                    failures,
                )
                return CircuitStatus(
                    open=True,
                    failures=failures,
                    open_until=open_until,
                    reason="circuit_open",
                )
            return CircuitStatus(open=False, failures=failures, open_until=None)
        except Exception:
            logger.debug("Redis circuit write failed", exc_info=True)

    global _mem_open_until
    with _lock:
        _mem_failures.append(now)
        recent = _prune(_mem_failures, window_sec=float(cooldown), now=now)
        _mem_failures[:] = recent
        if len(recent) >= threshold:
            _mem_open_until = now + cooldown
            logger.warning(
                "Claude circuit OPEN for %ss after %s failures (memory)",
                cooldown,
                len(recent),
            )
            return CircuitStatus(
                open=True,
                failures=len(recent),
                open_until=_mem_open_until,
                reason="circuit_open",
            )
        return CircuitStatus(open=False, failures=len(recent), open_until=None)


def record_claude_success() -> None:
    """Clear failure window on success (half-open recovery)."""
    client = _get_redis()
    if client is not None:
        try:
            client.delete(f"{_PREFIX}:fails")
            return
        except Exception:
            logger.debug("Redis circuit clear failed", exc_info=True)
    with _lock:
        _mem_failures.clear()


def reset_circuit_for_tests() -> None:
    global _mem_open_until
    with _lock:
        _mem_failures.clear()
        _mem_open_until = 0.0


__all__ = [
    "CircuitStatus",
    "is_claude_circuit_open",
    "record_claude_failure",
    "record_claude_success",
    "reset_circuit_for_tests",
]
