"""Structured request timing for POST /api/mock-attempts (stdout JSON)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any


def elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)


@dataclass
class MockStartTiming:
    """Breakdown of access gates + start_mock DB/RPC/cache work."""

    duration_ms: int = 0
    access_guest_ms: int = 0
    access_premium_ms: int = 0
    fetch_start_context_ms: int = 0
    catalog_validate_ms: int = 0
    abandon_existing_ms: int = 0
    insert_mock_attempt_ms: int = 0
    fetch_progress_bundle_ms: int = 0
    progress_from_bundle_ms: int = 0
    start_module_ms: int = 0
    start_module_find_ms: int = 0
    start_module_abandon_ms: int = 0
    start_module_insert_ms: int = 0
    update_current_module_ms: int = 0
    progress_rebuild_ms: int = 0
    unlock_snapshot_ms: int = 0
    write_cache_ms: int = 0
    resumed: bool | None = None
    force_new: bool | None = None
    start_module: str | None = None
    start_part: int | None = None

    def to_log_fields(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in asdict(self).items():
            if value is None:
                continue
            if isinstance(value, bool):
                out[key] = value
                continue
            if value == 0 and key != "duration_ms":
                continue
            out[key] = value
        return out
