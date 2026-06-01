"""Pydantic schemas for the Writing module API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

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
    min_words: int = 0
    submitted_at: datetime | None = None
    saved_for_review: bool = False
