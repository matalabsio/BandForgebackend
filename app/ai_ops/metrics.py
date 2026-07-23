"""Redis / in-memory metrics store for AI evaluation ops."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from app.cache.hybrid_cache import redis_status
from app.config import get_settings

logger = logging.getLogger(__name__)

_PREFIX = "bf:ai"
_FAILURE_LIST_MAX = 25

_mem_counters: dict[str, int] = {}
_mem_failures: list[dict[str, Any]] = []
_lock = Lock()


def _day_key() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def _month_key() -> str:
    return datetime.now(UTC).strftime("%Y%m")


def _counter_key(metric: str, period: str) -> str:
    return f"{_PREFIX}:ctr:{period}:{metric}"


def _get_redis():
    from app.cache.hybrid_cache import _get_redis as get_redis_client

    return get_redis_client()


def incr(metric: str, *, amount: int = 1, periods: tuple[str, ...] = ("day", "month")) -> None:
    if amount == 0:
        return
    day = _day_key()
    month = _month_key()
    period_ids = {"day": day, "month": month}
    client = _get_redis()
    for period in periods:
        pid = period_ids[period]
        key = _counter_key(metric, pid)
        if client is not None:
            try:
                client.incrby(key, amount)
                # Expire day keys ~ 3 days, month ~ 45 days
                ttl = 3 * 86400 if period == "day" else 45 * 86400
                client.expire(key, ttl)
                continue
            except Exception:
                logger.debug("Redis incr failed for %s", key, exc_info=True)
        with _lock:
            _mem_counters[key] = int(_mem_counters.get(key, 0)) + amount


def get_counter(metric: str, *, period: str = "day") -> int:
    pid = _day_key() if period == "day" else _month_key()
    key = _counter_key(metric, pid)
    client = _get_redis()
    if client is not None:
        try:
            raw = client.get(key)
            if raw is not None:
                return int(raw)
        except Exception:
            logger.debug("Redis get failed for %s", key, exc_info=True)
    with _lock:
        return int(_mem_counters.get(key, 0))


def get_counters(
    metrics: list[str],
    *,
    period: str = "day",
) -> dict[str, int]:
    """Batch-read counters with a single MGET (falls back to memory)."""
    if not metrics:
        return {}
    pid = _day_key() if period == "day" else _month_key()
    keys = [_counter_key(metric, pid) for metric in metrics]
    out: dict[str, int] = {metric: 0 for metric in metrics}
    client = _get_redis()
    if client is not None:
        try:
            raw_values = client.mget(keys)
            for metric, raw in zip(metrics, raw_values or [], strict=False):
                if raw is not None:
                    out[metric] = int(raw)
            return out
        except Exception:
            logger.debug("Redis MGET failed", exc_info=True)
    with _lock:
        for metric, key in zip(metrics, keys, strict=False):
            out[metric] = int(_mem_counters.get(key, 0))
    return out


def get_day_month_counters(metric: str) -> tuple[int, int]:
    """Read day + month counters for one metric in a single MGET."""
    day_key = _counter_key(metric, _day_key())
    month_key = _counter_key(metric, _month_key())
    client = _get_redis()
    if client is not None:
        try:
            raw_day, raw_month = client.mget([day_key, month_key])
            return (
                int(raw_day) if raw_day is not None else 0,
                int(raw_month) if raw_month is not None else 0,
            )
        except Exception:
            logger.debug("Redis day/month MGET failed", exc_info=True)
    with _lock:
        return (
            int(_mem_counters.get(day_key, 0)),
            int(_mem_counters.get(month_key, 0)),
        )


def record_failure(provider: str, reason: str) -> None:
    entry = {
        "provider": provider,
        "reason": (reason or "unknown")[:240],
        "at": datetime.now(UTC).isoformat(),
    }
    client = _get_redis()
    list_key = f"{_PREFIX}:failures"
    if client is not None:
        try:
            import json

            client.lpush(list_key, json.dumps(entry))
            client.ltrim(list_key, 0, _FAILURE_LIST_MAX - 1)
            client.expire(list_key, 7 * 86400)
            return
        except Exception:
            logger.debug("Redis failure list push failed", exc_info=True)
    with _lock:
        _mem_failures.insert(0, entry)
        del _mem_failures[_FAILURE_LIST_MAX:]


def recent_failures(limit: int = 10) -> list[dict[str, Any]]:
    client = _get_redis()
    list_key = f"{_PREFIX}:failures"
    if client is not None:
        try:
            import json

            raw_items = client.lrange(list_key, 0, max(0, limit - 1))
            out: list[dict[str, Any]] = []
            for raw in raw_items or []:
                try:
                    item = json.loads(raw)
                    if isinstance(item, dict):
                        out.append(item)
                except Exception:
                    continue
            return out
        except Exception:
            logger.debug("Redis failure list read failed", exc_info=True)
    with _lock:
        return list(_mem_failures[:limit])


def reset_memory_metrics_for_tests() -> None:
    """Clear in-process counters (unit tests only)."""
    with _lock:
        _mem_counters.clear()
        _mem_failures.clear()


def record_eval_outcome(
    *,
    provider: str,
    success: bool,
    latency_ms: int,
    retries: int = 0,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
    is_stub: bool = False,
    is_cache_hit: bool = False,
) -> None:
    incr("calls")
    if is_stub:
        incr("stub_calls")
    if is_cache_hit:
        incr("cache_hits")
    else:
        incr("cache_misses")
    if success:
        incr("success")
    else:
        incr("errors")
        record_failure(provider, "evaluation_failed")
    if retries > 0:
        incr("retries", amount=retries)
    if latency_ms > 0:
        incr("latency_ms_sum", amount=latency_ms)
        incr("latency_ms_count")
    if tokens_in > 0:
        incr("tokens_in", amount=tokens_in)
    if tokens_out > 0:
        incr("tokens_out", amount=tokens_out)
    if cost_usd > 0:
        incr("cost_usd_micros", amount=int(round(cost_usd * 1_000_000)))

    provider_key = provider.replace(":", "_")
    incr(f"provider:{provider_key}:calls")
    if success:
        incr(f"provider:{provider_key}:success")
    else:
        incr(f"provider:{provider_key}:errors")


def snapshot_today() -> dict[str, Any]:
    from app.perf.timing import timed_call

    metric_names = [
        "calls",
        "success",
        "errors",
        "retries",
        "latency_ms_sum",
        "latency_ms_count",
        "cost_usd_micros",
        "stub_calls",
        "cache_hits",
        "cache_misses",
        "tokens_in",
        "tokens_out",
    ]
    counters = timed_call(
        "ai.snapshot.mget",
        lambda: get_counters(metric_names, period="day"),
    )
    calls = counters["calls"]
    success = counters["success"]
    errors = counters["errors"]
    retries = counters["retries"]
    latency_sum = counters["latency_ms_sum"]
    latency_count = counters["latency_ms_count"]
    cost_micros = counters["cost_usd_micros"]
    avg_latency = (
        round(latency_sum / latency_count, 1) if latency_count > 0 else 0.0
    )
    success_rate = round((success / calls) * 100.0, 1) if calls > 0 else 100.0
    retry_rate = round((retries / calls) * 100.0, 1) if calls > 0 else 0.0
    status = timed_call("ai.snapshot.redis_status", redis_status)
    return {
        "period": "day",
        "day": _day_key(),
        "calls": calls,
        "success": success,
        "errors": errors,
        "retries": retries,
        "stub_calls": counters["stub_calls"],
        "cache_hits": counters["cache_hits"],
        "cache_misses": counters["cache_misses"],
        "tokens_in": counters["tokens_in"],
        "tokens_out": counters["tokens_out"],
        "estimated_cost_usd": round(cost_micros / 1_000_000.0, 4),
        "avg_latency_ms": avg_latency,
        "success_rate_pct": success_rate,
        "retry_rate_pct": retry_rate,
        "redis_status": status,
        "generated_at": datetime.now(UTC).isoformat(),
    }


__all__ = [
    "get_counter",
    "get_counters",
    "get_day_month_counters",
    "incr",
    "recent_failures",
    "record_eval_outcome",
    "record_failure",
    "reset_memory_metrics_for_tests",
    "snapshot_today",
]
