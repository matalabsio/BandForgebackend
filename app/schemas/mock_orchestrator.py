"""Pydantic models for mock exam orchestration."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.test_engine import TestSummary

ModuleName = Literal["reading", "listening", "writing", "speaking"]
ModuleProgressStatus = Literal["locked", "available", "in_progress", "completed"]


class ModuleProgress(BaseModel):
    module: ModuleName
    sequence_order: int
    status: ModuleProgressStatus
    duration_minutes: int
    is_enabled: bool
    band: float | None = None
    test_attempt_id: UUID | None = None
    part: int | None = None


class StartMockRequest(BaseModel):
    mock_test_id: UUID
    force_new: bool = False


class MockUnlockSnapshot(BaseModel):
    """Minimal progress for assert_module_unlocked (no scores or answers)."""

    done_parts: dict[str, list[int]] = Field(default_factory=dict)
    current_module: ModuleName | None = None
    module_status: dict[str, ModuleProgressStatus] = Field(default_factory=dict)


class MockProgressCachePayload(BaseModel):
    progress: MockAttemptProgress
    unlock: MockUnlockSnapshot


class MockAttemptProgress(BaseModel):
    mock_attempt_id: UUID
    mock_test_id: UUID
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    current_module: ModuleName | None = None
    modules: list[ModuleProgress] = Field(default_factory=list)
    next_module: ModuleName | None = None
    next_part: int | None = None
    aggregate_band: float | None = None


class StartMockResponse(BaseModel):
    mock_attempt_id: UUID
    mock_test: TestSummary
    current_module: ModuleName
    module_attempt_id: UUID
    part: int | None = None
    resumed: bool = False
    progress: MockAttemptProgress | None = None


class MockCatalogItem(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    catalog_number: int | None = None
    modules_enabled: list[ModuleName] = Field(default_factory=list)
    listening_parts: int = 0
    reading_passages: int = 0
    writing_tasks: int = 2


class SectionScore(BaseModel):
    test_attempt_id: UUID
    module: ModuleName
    part: int | None = None
    raw_score: int | None = None
    total_questions: int | None = None
    band: float | None = None


class MockAttemptSummary(MockAttemptProgress):
    sections: list[SectionScore] = Field(default_factory=list)
    reading_band: float | None = None
    listening_band: float | None = None
    writing_band: float | None = None


class InProgressMockAttempt(BaseModel):
    mock_attempt_id: UUID
    mock_test_id: UUID
    status: str
    current_module: ModuleName | None = None


class MockAttemptHistoryItem(BaseModel):
    mock_attempt_id: UUID
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    aggregate_band: float | None = None
    reading_band: float | None = None
    listening_band: float | None = None


class MockAttemptHistoryLiteItem(BaseModel):
    """Lightweight history row — no per-module score rollups."""

    mock_attempt_id: UUID
    status: str
    started_at: datetime
    completed_at: datetime | None = None


class CheckpointSkillEntry(BaseModel):
    correct: int
    total: int
    pct: float


class MockCheckpointResponse(BaseModel):
    """Lightweight payload for post-section checkpoint UI (one round trip)."""

    attempt_id: UUID
    band: float
    raw_score: int
    total_questions: int
    skill_breakdown: dict[str, CheckpointSkillEntry] = Field(default_factory=dict)
    status: str
    next_module: ModuleName | None = None
    next_part: int | None = None
    reading_band: float | None = None
    listening_band: float | None = None
    modules: list[ModuleProgress] = Field(default_factory=list)
