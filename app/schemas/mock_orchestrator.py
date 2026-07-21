"""Pydantic models for mock exam orchestration."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.test_engine import TestSummary
from app.speaking.schemas import ReleaseState, SpeakingReviewerPublic

ModuleName = Literal["reading", "listening", "writing", "speaking"]
ModuleProgressStatus = Literal["locked", "available", "in_progress", "completed"]
ModuleResultSource = Literal[
    "final",
    "ai_estimate",
    "processing",
    "failed",
    "awaiting_examiner",
    "unavailable",
]


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


class ModuleResultState(BaseModel):
    band: float | None = None
    source: ModuleResultSource


class MockAttemptSummary(MockAttemptProgress):
    sections: list[SectionScore] = Field(default_factory=list)
    reading_band: float | None = None
    listening_band: float | None = None
    writing_band: float | None = None
    speaking_band: float | None = None
    provisional_aggregate_band: float | None = None
    aggregate_is_provisional: bool = False
    has_pending_reviews: bool = False
    module_result_states: dict[ModuleName, ModuleResultState] = Field(
        default_factory=dict
    )


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
    writing_band: float | None = None
    speaking_band: float | None = None


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


class ModuleReviewQuestion(BaseModel):
    """One checked question in a module review (shared by listening + reading)."""

    question_id: UUID
    question_number: int
    question_type: str
    prompt: str
    user_answer: str
    correct_answer: str
    is_correct: bool
    explanation: str = ""


class ModuleReviewGroup(BaseModel):
    """A part (listening) or passage-section (reading) with its sub-score."""

    label: str
    raw_score: int
    total_questions: int
    questions: list[ModuleReviewQuestion] = Field(default_factory=list)


class ModuleReviewResponse(BaseModel):
    """Full-module answer review after every part/passage is submitted."""

    module: ModuleName
    mock_attempt_id: UUID
    raw_score: int
    total_questions: int
    groups: list[ModuleReviewGroup] = Field(default_factory=list)
    next_module: ModuleName | None = None
    next_part: int | None = None


class WritingTaskReview(BaseModel):
    """One writing task inside a module review (AI estimate now, human later)."""

    attempt_id: UUID
    part: int
    prompt: str
    essay: str
    word_count: int
    ai_band: float | None = None
    criteria: dict[str, float] = Field(default_factory=dict)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)


class WritingModuleReviewResponse(BaseModel):
    """Both writing tasks with AI feedback and one persona summary."""

    mock_attempt_id: UUID
    tasks: list[WritingTaskReview] = Field(default_factory=list)
    ai_band: float | None = None
    persona_message: str
    ai_available: bool = True
    next_module: ModuleName | None = None
    next_part: int | None = None


class SpeakingModuleReviewResponse(BaseModel):
    """Speaking release status with authoritative human result after release."""

    mock_attempt_id: UUID
    attempt_id: UUID
    part: int
    duration_seconds: int | None = None
    duration_hint_seconds: int | None = None
    ai_band: float | None = None
    overall_band: float | None = None
    score_source: Literal[
        "human", "ai_estimate", "processing", "failed", "unavailable"
    ]
    ai_status: str | None = None
    evaluation_status: str | None = None
    criteria: dict[str, float] = Field(default_factory=dict)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    next_band_advice: str | None = None
    prompts: list[str] = Field(default_factory=list)
    delivery_notes: list[str] = Field(default_factory=list)
    persona_message: str
    release_state: ReleaseState
    report_available: bool
    released_at: datetime | None = None
    approval_version: int = 0
    reviewer: SpeakingReviewerPublic | None = None
    result_route: Literal["pending", "report"]
    next_module: ModuleName | None = None
    next_part: int | None = None
