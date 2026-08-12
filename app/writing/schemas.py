"""Pydantic schemas for the Writing module API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.diagnostic.evaluation_schemas import (
    GrammarMistake,
    SpellingMistake,
    StrongSpan,
    VocabularyHighlight,
)
from app.schemas.test_engine import TestSummary


class WritingTaskQuestion(BaseModel):
    id: UUID
    question_number: int
    question_type: str
    prompt: str
    part: int
    options: dict[str, Any] | None = None


class StartWritingResponse(BaseModel):
    attempt_id: UUID
    started_at: datetime
    server_time: datetime
    status: str
    module: str = "writing"
    part: int
    duration_seconds: int
    resumed: bool = False
    test: TestSummary | None = None
    task: WritingTaskQuestion | None = None
    saved_answer: str | None = None


class AutosaveRequest(BaseModel):
    question_id: UUID
    user_answer: str = Field(min_length=0, max_length=20_000)


class AutosaveResponse(BaseModel):
    ok: bool = True
    question_id: UUID
    saved_at: datetime


class SubmitAnswer(BaseModel):
    question_id: UUID
    user_answer: str = Field(min_length=0, max_length=20_000)


class SubmitWritingRequest(BaseModel):
    answers: list[SubmitAnswer] = Field(default_factory=list)
    on_expiry: bool = False


class SubmitWritingResponse(BaseModel):
    attempt_id: UUID
    status: str
    submitted_at: datetime
    part: int
    word_count: int = 0
    band: float | None = None
    min_words: int = 0
    saved_for_review: bool = False
    next_part: int | None = None
    mock_next_module: str | None = None
    mock_next_part: int | None = None
    mock_writing_complete: bool = False


class WritingSessionTaskSummary(BaseModel):
    attempt_id: UUID
    part: int
    human_band: float | None = None
    review_status: str
    ai_status: str | None = None
    ai_band: float | None = None


class WritingReviewResponse(BaseModel):
    attempt_id: UUID
    status: str
    module: str = "writing"
    part: int
    test_title: str | None = None
    question_type: str
    prompt: str
    options: dict[str, Any] | None = None
    user_answer: str
    word_count: int
    band: float | None = None
    ai_band: float | None = None
    ai_available: bool = False
    ai_status: str | None = None
    band_source: str = "none"
    human_verified: bool = False
    reviewer_notes: str | None = None
    ai_criteria: dict[str, float] = Field(default_factory=dict)
    ai_strengths: list[str] = Field(default_factory=list)
    ai_improvements: list[str] = Field(default_factory=list)
    ai_model_name: str | None = None
    ai_provider: str | None = None
    spelling_mistakes: list[SpellingMistake] = Field(default_factory=list)
    grammar_mistakes: list[GrammarMistake] = Field(default_factory=list)
    next_band_advice: str = ""
    confidence: float | None = None
    vocabulary_highlights: list[VocabularyHighlight] = Field(default_factory=list)
    strong_spans: list[StrongSpan] = Field(default_factory=list)
    min_words: int = 0
    submitted_at: datetime | None = None
    saved_for_review: bool = False
    session_tasks: list[WritingSessionTaskSummary] = Field(default_factory=list)


class WritingPendingResponse(BaseModel):
    attempt_id: UUID
    status: str
    review_status: str
    human_band: float | None = None
    ai_status: str | None = None
    ai_band: float | None = None
    ai_available: bool = False
    submitted_at: datetime | None = None
    message: str
    session_tasks: list[WritingSessionTaskSummary] = Field(default_factory=list)
