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
    request_id: str | None = None
    auth_ms: int = 0
    attempt_ms: int = 0
    validate_ms: int = 0
    upsert_ms: int = 0
    attempt_fetch_ms: int = 0
    question_validate_ms: int = 0
    answer_upsert_ms: int = 0
    db_query_count: int = 0

    def to_log_fields(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.request_id:
            out["request_id"] = self.request_id
            out["endpoint"] = "reading-autosave"
        if self.auth_ms:
            out["auth_ms"] = self.auth_ms
        if self.attempt_fetch_ms or self.attempt_ms:
            out["attempt_fetch_ms"] = self.attempt_fetch_ms or self.attempt_ms
        if self.question_validate_ms or self.validate_ms:
            out["question_validate_ms"] = (
                self.question_validate_ms or self.validate_ms
            )
        if self.answer_upsert_ms or self.upsert_ms:
            out["answer_upsert_ms"] = self.answer_upsert_ms or self.upsert_ms
        if self.db_query_count:
            out["db_query_count"] = self.db_query_count
        if self.duration_ms:
            out["total_ms"] = self.duration_ms
            out["duration_ms"] = self.duration_ms
        # Legacy field names for existing log parsers
        if self.attempt_ms:
            out["attempt_ms"] = self.attempt_ms
        if self.validate_ms:
            out["validate_ms"] = self.validate_ms
        if self.upsert_ms:
            out["upsert_ms"] = self.upsert_ms
        db_ms = (
            (self.attempt_fetch_ms or self.attempt_ms)
            + (self.question_validate_ms or self.validate_ms)
            + (self.answer_upsert_ms or self.upsert_ms)
        )
        if db_ms:
            out["db_ms"] = db_ms
        return out


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
