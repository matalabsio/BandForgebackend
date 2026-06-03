"""Sub-phase timings for mock progress rebuild on module submit."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any


def _elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)


@dataclass
class MockProgressTiming:
    """Breakdown of on_module_attempt_completed + _finalize_mock_progress_after_submit."""

    progress_ms: int = 0
    progress_fetch_bundle_ms: int = 0
    progress_parts_check_ms: int = 0
    progress_update_mock_attempt_ms: int = 0
    progress_finalize_ms: int = 0
    progress_finalize_invalidate_ms: int = 0
    progress_finalize_invalidate_history_ms: int = 0
    progress_finalize_fetch_bundle_ms: int = 0
    progress_finalize_compute_ms: int = 0
    progress_finalize_write_cache_ms: int = 0
    serialize_progress_ms: int = 0
    set_progress_cache_ms: int = 0
    set_unlock_cache_ms: int = 0
    set_session_cache_ms: int = 0
    progress_fetch_bundle_count: int = 0

    def to_log_fields(self) -> dict[str, Any]:
        out = asdict(self)
        return {k: v for k, v in out.items() if v != 0 and v is not None}
