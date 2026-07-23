"""Bounded concurrency helpers for read-only admin fan-out."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, TypeVar

T = TypeVar("T")


def run_parallel(
    jobs: dict[str, Callable[[], T]],
    *,
    max_workers: int | None = None,
) -> dict[str, T]:
    """Run independent callables concurrently; preserve key→result mapping.

    Exceptions from any job propagate after cancellation of pending work.
    """
    if not jobs:
        return {}
    if len(jobs) == 1:
        key, fn = next(iter(jobs.items()))
        return {key: fn()}

    workers = max(1, min(len(jobs), max_workers or len(jobs)))
    out: dict[str, T] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn): key for key, fn in jobs.items()}
        try:
            for fut in as_completed(futures):
                key = futures[fut]
                out[key] = fut.result()
        except Exception:
            for fut in futures:
                fut.cancel()
            raise
    return out
