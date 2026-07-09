"""Pydantic schemas for the Reading module API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.test_engine import TestSummary


class ReadingQuestion(BaseModel):
    id: UUID
    question_number: int
    display_number: int | None = None
    question_type: str
    prompt: str
    options: list[dict[str, str]] | None = None
    skill_tag: str | None = None


class StartReadingResponse(BaseModel):
    attempt_id: UUID
    started_at: datetime
    server_time: datetime
    status: str
    module: str = "reading"
    duration_seconds: int
    resumed: bool = False
    test: TestSummary | None = None
    passage_text: str | None = None
    questions: list[ReadingQuestion] = Field(default_factory=list)
    saved_answers: dict[str, str] = Field(default_factory=dict)


class ReadingQuestionsResponse(BaseModel):
    test: TestSummary
    module: str = "reading"
    passage_text: str | None = None
    questions: list[ReadingQuestion]
    duration_seconds: int


class AutosaveRequest(BaseModel):
    question_id: UUID
    user_answer: str = Field(min_length=0, max_length=500)


class AutosaveResponse(BaseModel):
    ok: bool = True
    question_id: UUID
    saved_at: datetime


class SubmitAnswer(BaseModel):
    question_id: UUID
    user_answer: str = Field(min_length=0, max_length=500)


class SubmitReadingRequest(BaseModel):
    answers: list[SubmitAnswer] = Field(default_factory=list)


class SkillBreakdownEntry(BaseModel):
    correct: int
    total: int
    pct: float


class QuestionReviewItem(BaseModel):
    question_id: UUID
    question_number: int
    question_type: str
    prompt: str
    user_answer: str
    correct_answer: str
    is_correct: bool
    explanation: str = ""


class ReadingScoreReport(BaseModel):
    attempt_id: UUID
    status: str
    module: str = "reading"
    test_title: str | None = None
    submitted_at: datetime | None = None
    raw_score: int
    total_questions: int
    band: float
    late_submission: bool = False
    skill_breakdown: dict[str, SkillBreakdownEntry] = Field(default_factory=dict)
    questions: list[QuestionReviewItem] = Field(default_factory=list)


class SubmitReadingResponse(BaseModel):
    attempt_id: UUID
    status: str
    submitted_at: datetime
    raw_score: int
    total_questions: int
    band: float
    late_submission: bool = False
    skill_breakdown: dict[str, SkillBreakdownEntry] = Field(default_factory=dict)
    mock_next_module: str | None = None
    mock_next_part: int | None = None
    mock_reading_complete: bool = False
