"""Pydantic models for the Speaking module API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.test_engine import TestSummary


class SpeakingQuestionPublic(BaseModel):
    id: UUID
    question_number: int
    question_type: str
    prompt: str
    part: int
    duration_hint_sec: int | None = None
    part_label: str | None = None


class StartSpeakingResponse(BaseModel):
    attempt_id: UUID
    started_at: datetime
    server_time: datetime
    status: str
    part: int
    duration_seconds: int
    resumed: bool
    test: TestSummary
    question: SpeakingQuestionPublic
    student_name: str | None = None


class SubmitSpeakingResponse(BaseModel):
    attempt_id: UUID
    status: str
    submitted_at: datetime
    review_id: UUID
    mock_next_module: str | None = None
    mock_next_part: int | None = None
    mock_speaking_complete: bool = False
    message: str = (
        "Your recording has been submitted. A certified examiner will review it "
        "within 24 hours."
    )


class SpeakingPendingResponse(BaseModel):
    attempt_id: UUID
    status: str
    review_status: str
    human_band: float | None = None
    ai_status: str | None = None
    submitted_at: datetime | None = None
    student_name: str | None = None
    message: str


class SpeakingHumanCriteria(BaseModel):
    fluency: float
    lexical: float
    grammar: float
    pronunciation: float


class SpeakingFluencyMetrics(BaseModel):
    words_per_minute: float | None = None
    total_speaking_seconds: float | None = None
    long_pauses: int | None = None
    response_count: int | None = None
    questions_asked: int | None = None


class SpeakingPauseMarker(BaseModel):
    after_word: str
    gap_sec: float


class SpeakingReportResponse(BaseModel):
    """Human-released student speaking report (rich AI + human criteria)."""

    attempt_id: UUID
    status: str
    review_status: str
    overall_band: float
    human_verified: bool = True
    human_criteria_scores: SpeakingHumanCriteria | None = None
    ai_band: float | None = None
    fluency: float | None = None
    lexical: float | None = None
    grammar: float | None = None
    pronunciation: float | None = None
    evaluation: dict[str, Any] | None = None
    fluency_metrics: SpeakingFluencyMetrics | None = None
    pause_markers: list[SpeakingPauseMarker] = Field(default_factory=list)
    transcript: str | None = None
    audio_play_url: str | None = None
    ai_status: str | None = None
    prompt_version: str | None = None
    provider_asr: str | None = None
    provider_eval: str | None = None
    model_asr: str | None = None
    model_eval: str | None = None
    submitted_at: datetime | None = None
    student_name: str | None = None
    reviewer_notes: str | None = None
    part: int = 1

