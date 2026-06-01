"""Hybrid cache: in-memory first, Redis optional shared layer."""

from __future__ import annotations

import json
import time
from contextvars import ContextVar
from threading import Lock
from typing import Any

from app.config import get_settings

try:
    from redis import Redis
except Exception:  # pragma: no cover - optional dependency
    Redis = None  # type: ignore[assignment]

_cache_hit: ContextVar[bool] = ContextVar("bf_cache_hit", default=False)


_memory_store: dict[str, tuple[float, str]] = {}
_memory_lock = Lock()
_redis_client: Any | None = None
_redis_attempted = False


def _get_redis() -> Any | None:
    global _redis_client, _redis_attempted
    if _redis_attempted:
        return _redis_client
    _redis_attempted = True
    settings = get_settings()
    if not settings.redis_url or Redis is None:
        _redis_client = None
        return None
    try:
        _redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
        _redis_client.ping()
    except Exception:
        _redis_client = None
    return _redis_client


def _mem_get(key: str) -> str | None:
    now = time.time()
    with _memory_lock:
        hit = _memory_store.get(key)
        if not hit:
            return None
        exp, value = hit
        if exp < now:
            _memory_store.pop(key, None)
            return None
        return value


def _mem_set(key: str, value: str, ttl_seconds: int) -> None:
    with _memory_lock:
        _memory_store[key] = (time.time() + max(1, ttl_seconds), value)


def reset_cache_hit() -> None:
    _cache_hit.set(False)


def mark_cache_hit() -> None:
    _cache_hit.set(True)


def was_cache_hit() -> bool:
    return _cache_hit.get()


def get_json(key: str) -> Any | None:
    cached = _mem_get(key)
    if cached is not None:
        mark_cache_hit()
        try:
            return json.loads(cached)
        except Exception:
            return None

    client = _get_redis()
    if not client:
        return None
    try:
        raw = client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    mark_cache_hit()
    _mem_set(key, raw, 5)
    try:
        return json.loads(raw)
    except Exception:
        return None


def set_json(key: str, value: Any, ttl_seconds: int) -> None:
    try:
        encoded = json.dumps(value, separators=(",", ":"), default=str)
    except Exception:
        return
    _mem_set(key, encoded, ttl_seconds)
    client = _get_redis()
    if not client:
        return
    try:
        client.setex(key, max(1, ttl_seconds), encoded)
    except Exception:
        return


def delete_many(keys: list[str]) -> None:
    with _memory_lock:
        for key in keys:
            _memory_store.pop(key, None)
    client = _get_redis()
    if not client or not keys:
        return
    try:
        client.delete(*keys)
    except Exception:
        return


def invalidate_prefix(prefix: str) -> None:
    with _memory_lock:
        doomed = [k for k in _memory_store if k.startswith(prefix)]
        for key in doomed:
            _memory_store.pop(key, None)
    client = _get_redis()
    if not client:
        return
    try:
        for key in client.scan_iter(match=f"{prefix}*"):
            client.delete(key)
    except Exception:
        return


def redis_status() -> str:
    client = _get_redis()
    if not client:
        return "off"
    try:
        return "ok" if client.ping() else "error"
    except Exception:
        return "error"
