"""Lightweight reliability metrics (Phase 4) — Redis + in-memory fallback.

Trackers: empty_hub_assignment, scoring_failure, planner_failure,
API latency samples, completion (task_done / hub_complete).
"""

from __future__ import annotations

import json
import logging
from collections import deque
from datetime import UTC, datetime
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_PREFIX = "bf:rel"
_FAILURE_LIST_MAX = 40
_LATENCY_SAMPLE_MAX = 200

_mem_counters: dict[str, int] = {}
_mem_events: deque[dict[str, Any]] = deque(maxlen=_FAILURE_LIST_MAX)
_mem_latency: dict[str, deque[float]] = {}
_mem_assigned_users: set[str] = set()
_lock = Lock()

TRACKED_ROUTES = (
    "/api/learning/profile",
    "/api/learning/today",
    "/api/practice/hubs",
    "/api/practice/hubs/",  # detail + exercise prefix match
)


def _day_key() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def _get_redis():
    try:
        from app.cache.hybrid_cache import _get_redis as get_redis_client

        return get_redis_client()
    except Exception:
        return None


def _counter_key(metric: str) -> str:
    return f"{_PREFIX}:ctr:{_day_key()}:{metric}"


def incr(metric: str, *, amount: int = 1) -> None:
    if amount == 0:
        return
    key = _counter_key(metric)
    client = _get_redis()
    if client is not None:
        try:
            client.incrby(key, amount)
            client.expire(key, 3 * 86400)
            return
        except Exception:
            logger.debug("reliability incr failed %s", key, exc_info=True)
    with _lock:
        _mem_counters[key] = int(_mem_counters.get(key, 0)) + amount


def mark_tasks_assigned_once(user_id: str, *, amount: int = 1) -> bool:
    """Bump tasks_assigned_today once per user per UTC day.

    Returns True when this call performed the increment.
    """
    if amount <= 0:
        amount = 1
    uid = str(user_id).strip()
    if not uid:
        return False
    day = _day_key()
    dedupe_key = f"{_PREFIX}:assigned:{day}:{uid}"
    client = _get_redis()
    if client is not None:
        try:
            # SET NX — first serve of the day wins
            ok = client.set(dedupe_key, "1", nx=True, ex=3 * 86400)
            if ok:
                incr("tasks_assigned_today", amount=amount)
                return True
            return False
        except Exception:
            logger.debug("reliability assigned-once failed", exc_info=True)
    with _lock:
        if dedupe_key in _mem_assigned_users:
            return False
        _mem_assigned_users.add(dedupe_key)
        # Bound memory growth (keys include day; prune old days opportunistically)
        if len(_mem_assigned_users) > 50_000:
            stale = [k for k in _mem_assigned_users if f":{day}:" not in k]
            for k in stale[: max(1, len(stale) // 2)]:
                _mem_assigned_users.discard(k)
    incr("tasks_assigned_today", amount=amount)
    return True


def get_counter(metric: str) -> int:
    key = _counter_key(metric)
    client = _get_redis()
    if client is not None:
        try:
            raw = client.get(key)
            if raw is not None:
                return int(raw)
        except Exception:
            logger.debug("reliability get failed %s", key, exc_info=True)
    with _lock:
        return int(_mem_counters.get(key, 0))


def record_event(
    kind: str,
    *,
    detail: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Record a reliability incident and bump its counter."""
    incr(kind)
    payload = {
        "ts": datetime.now(UTC).isoformat(),
        "kind": kind,
        "detail": detail or "",
        "meta": meta or {},
        "event": f"reliability.{kind}",
    }
    print(json.dumps(payload))
    list_key = f"{_PREFIX}:events:{_day_key()}"
    client = _get_redis()
    if client is not None:
        try:
            client.lpush(list_key, json.dumps(payload))
            client.ltrim(list_key, 0, _FAILURE_LIST_MAX - 1)
            client.expire(list_key, 3 * 86400)
            return
        except Exception:
            logger.debug("reliability event push failed", exc_info=True)
    with _lock:
        _mem_events.appendleft(payload)


def record_latency(route: str, duration_ms: float) -> None:
    """Store latency sample for p50/p95 (hot learning/practice routes)."""
    path = route.split("?")[0]
    tracked = False
    for prefix in TRACKED_ROUTES:
        if path == prefix or path.startswith(prefix.rstrip("/") + "/") or path == prefix.rstrip("/"):
            tracked = True
            break
    if not tracked and path.startswith("/api/practice/hubs"):
        tracked = True
    if not tracked:
        return

    # Normalize dynamic segments for aggregation
    key_route = path
    parts = path.strip("/").split("/")
    if len(parts) >= 4 and parts[0] == "api" and parts[1] == "practice" and parts[2] == "hubs":
        if len(parts) == 4:
            key_route = "/api/practice/hubs/{id}"
        elif "exercise" in parts:
            key_route = "/api/practice/hubs/{id}/exercise"

    sample_key = f"{_PREFIX}:lat:{_day_key()}:{key_route}"
    client = _get_redis()
    if client is not None:
        try:
            client.lpush(sample_key, str(round(duration_ms, 2)))
            client.ltrim(sample_key, 0, _LATENCY_SAMPLE_MAX - 1)
            client.expire(sample_key, 3 * 86400)
            return
        except Exception:
            logger.debug("reliability latency push failed", exc_info=True)
    with _lock:
        bucket = _mem_latency.setdefault(sample_key, deque(maxlen=_LATENCY_SAMPLE_MAX))
        bucket.appendleft(float(duration_ms))


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def latency_stats(route: str) -> dict[str, float | int | None]:
    sample_key = f"{_PREFIX}:lat:{_day_key()}:{route}"
    samples: list[float] = []
    client = _get_redis()
    if client is not None:
        try:
            raw = client.lrange(sample_key, 0, _LATENCY_SAMPLE_MAX - 1) or []
            samples = [float(x) for x in raw]
        except Exception:
            logger.debug("reliability latency read failed", exc_info=True)
    if not samples:
        with _lock:
            samples = list(_mem_latency.get(sample_key) or [])
    vals = sorted(samples)
    return {
        "n": len(vals),
        "p50_ms": round(_percentile(vals, 0.5) or 0, 2) if vals else None,
        "p95_ms": round(_percentile(vals, 0.95) or 0, 2) if vals else None,
    }


def recent_events(*, limit: int = 25) -> list[dict[str, Any]]:
    list_key = f"{_PREFIX}:events:{_day_key()}"
    client = _get_redis()
    if client is not None:
        try:
            raw = client.lrange(list_key, 0, limit - 1) or []
            out: list[dict[str, Any]] = []
            for item in raw:
                try:
                    out.append(json.loads(item))
                except Exception:
                    continue
            return out
        except Exception:
            logger.debug("reliability events read failed", exc_info=True)
    with _lock:
        return list(_mem_events)[:limit]


def _practice_ops_strip() -> dict[str, Any]:
    """Assignable hub counts by skill + recent hub completions."""
    hubs_by_skill: dict[str, int] = {
        "listening": 0,
        "reading": 0,
        "writing": 0,
        "speaking": 0,
    }
    hub_completions_7d = 0
    try:
        from app.practice.catalog import get_ordered_hub_ids_by_skill

        ordered = get_ordered_hub_ids_by_skill()
        for skill, ids in ordered.items():
            hubs_by_skill[str(skill)] = len(ids or [])
    except Exception:
        logger.debug("reliability practice catalog failed", exc_info=True)
    try:
        from datetime import timedelta

        from app.db.supabase_client import get_supabase

        since = (datetime.now(UTC) - timedelta(days=7)).isoformat()
        result = (
            get_supabase()
            .table("user_hub_progress")
            .select("id", count="exact")
            .eq("status", "completed")
            .gte("completed_at", since)
            .limit(1)
            .execute()
        )
        hub_completions_7d = int(getattr(result, "count", None) or 0)
    except Exception:
        logger.debug("reliability hub_completions_7d failed", exc_info=True)
    return {
        "hubs_by_skill": hubs_by_skill,
        "hub_completions_7d": hub_completions_7d,
    }


def _notification_ops_strip() -> dict[str, Any]:
    """Speaking notification outbox depth + recent failures."""
    try:
        from app.notifications.repository import outbox_ops_snapshot

        return outbox_ops_snapshot()
    except Exception:
        logger.debug("reliability notification strip failed", exc_info=True)
        return {
            "queued": 0,
            "failed_24h": 0,
            "by_channel": {},
        }


def snapshot() -> dict[str, Any]:
    metrics = [
        "empty_hub_assignment",
        "scoring_failure",
        "planner_failure",
        "task_done",
        "hub_complete",
        "tasks_assigned_today",
    ]
    counters = {m: get_counter(m) for m in metrics}
    done = counters.get("task_done", 0) + counters.get("hub_complete", 0)
    assigned = max(counters.get("tasks_assigned_today", 0), 1)
    # completion_rate uses task_done / rough assigned; also expose raw
    return {
        "day": _day_key(),
        "counters": counters,
        "completion_rate": round(done / assigned, 4) if assigned else None,
        "latency": {
            "/api/learning/profile": latency_stats("/api/learning/profile"),
            "/api/learning/today": latency_stats("/api/learning/today"),
            "/api/practice/hubs/{id}": latency_stats("/api/practice/hubs/{id}"),
            "/api/practice/hubs/{id}/exercise": latency_stats(
                "/api/practice/hubs/{id}/exercise"
            ),
        },
        "recent_events": recent_events(),
        "practice": _practice_ops_strip(),
        "notifications": _notification_ops_strip(),
    }
