"""Structured request timing for Listening API logs (stdout JSON)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import perf_counter
from typing import Any

from app.services.mock_progress_timing import MockProgressTiming


def _elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)


@dataclass
class ListeningStartTiming:
    duration_ms: int = 0
    unlock_source: str | None = None
    unlock_ms: int = 0
    attempt_ms: int = 0
    questions_source: str | None = None
    questions_ms: int = 0
    audio_presign_ms: int = 0

    def to_log_fields(self) -> dict[str, Any]:
        out = asdict(self)
        return {k: v for k, v in out.items() if v is not None}


@dataclass
class ListeningSubmitTiming:
    duration_ms: int = 0
    attempt_ms: int = 0
    scoring_query_ms: int = 0
    scoring_compute_ms: int = 0
    rpc_bundle_ms: int = 0
    progress_ms: int = 0
    progress_timing: MockProgressTiming | None = field(default=None, repr=False)

    def to_log_fields(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in asdict(self).items():
            if key == "progress_timing" or value is None:
                continue
            if value != 0:
                out[key] = value
        if self.progress_timing is not None:
            out.update(self.progress_timing.to_log_fields())
        return out


@dataclass
class _PhaseTimer:
    """Accumulates elapsed ms across multiple timed blocks."""

    total_ms: int = 0

    def add(self, started: float) -> None:
        self.total_ms += _elapsed_ms(started)
