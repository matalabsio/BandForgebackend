"""Structured request timing for Reading API logs (stdout JSON)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.mock_progress_timing import MockProgressTiming


@dataclass
class ReadingStartTiming:
    duration_ms: int = 0
    unlock_source: str | None = None
    unlock_ms: int = 0
    stale_cleanup_ms: int = 0
    attempt_ms: int = 0
    questions_source: str | None = None
    questions_ms: int = 0
    passage_ms: int = 0

    def to_log_fields(self) -> dict[str, Any]:
        out = asdict(self)
        return {k: v for k, v in out.items() if v is not None}


@dataclass
class ReadingAutosaveTiming:
    duration_ms: int = 0
    attempt_ms: int = 0
    validate_ms: int = 0
    upsert_ms: int = 0

    def to_log_fields(self) -> dict[str, Any]:
        out = asdict(self)
        return {k: v for k, v in out.items() if v != 0 and v is not None}


@dataclass
class ReadingSubmitTiming:
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
