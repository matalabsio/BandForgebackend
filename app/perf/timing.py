"""Structured timing helpers for Phase 1 performance instrumentation."""

from __future__ import annotations

import json
import os
from contextvars import ContextVar
from time import perf_counter
from typing import Any, Callable, TypeVar
from uuid import uuid4

T = TypeVar("T")

_request_id: ContextVar[str | None] = ContextVar("perf_request_id", default=None)
_query_count: ContextVar[int] = ContextVar("perf_query_count", default=0)


def is_perf_enabled() -> bool:
    return os.environ.get("PERF_LOG", "").strip() == "1"


def new_request_id() -> str:
    return str(uuid4())


def set_request_id(request_id: str) -> None:
    _request_id.set(request_id)


def get_request_id() -> str | None:
    return _request_id.get()


def reset_perf_context(request_id: str) -> None:
    _request_id.set(request_id)
    _query_count.set(0)


def get_query_count() -> int:
    return _query_count.get()


def _increment_query_count() -> None:
    _query_count.set(_query_count.get() + 1)


def perf_step_log(step: str, duration_ms: float) -> None:
    if not is_perf_enabled():
        return
    print(
        json.dumps(
            {
                "event": "perf",
                "request_id": get_request_id(),
                "step": step,
                "duration_ms": round(duration_ms, 2),
            }
        )
    )


def perf_summary(endpoint: str, request_id: str, **fields: Any) -> None:
    if not is_perf_enabled():
        return
    payload: dict[str, Any] = {
        "event": "perf",
        "endpoint": endpoint,
        "request_id": request_id,
        **fields,
    }
    print(json.dumps(payload))


class PerfTimer:
    """Simple step timer for route handlers."""

    def __init__(self, label: str) -> None:
        self.label = label
        self._start = perf_counter()

    def elapsed_ms(self) -> float:
        return round((perf_counter() - self._start) * 1000, 2)

    def log_step(self, step: str) -> float:
        ms = self.elapsed_ms()
        if is_perf_enabled():
            print(f"[{self.label}] {step}: {ms}ms")
        return ms


def timed_call(step: str, fn: Callable[[], T], *, count_query: bool = False) -> T:
    """Time any callable and emit a step log when PERF_LOG=1."""
    if not is_perf_enabled():
        return fn()

    t0 = perf_counter()
    try:
        return fn()
    finally:
        duration_ms = round((perf_counter() - t0) * 1000, 2)
        if count_query:
            _increment_query_count()
        perf_step_log(step, duration_ms)


def timed_supabase(step: str, fn: Callable[[], T]) -> T:
    """Time a Supabase call, increment query count, emit step log when PERF_LOG=1."""
    return timed_call(step, fn, count_query=True)
