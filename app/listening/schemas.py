"""Pydantic schemas for the Listening module API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.test_engine import TestSummary


IeltsPart = Literal[1, 2, 3, 4]


class ListeningQuestion(BaseModel):
    """One listening question with its own short audio."""

    id: UUID
    part: IeltsPart
    question_number: int
    question_type: str
    prompt: str
    instructions: str | None = None
    options: list[dict[str, str]] | None = None
    skill_tag: str | None = None
    audio_url: str | None = None
    audio_duration_seconds: float | None = None


class ListeningPart(BaseModel):
    """IELTS Listening section grouping (1..4)."""

    part: IeltsPart
    title: str
    context: str
    common_question_type: str
    questions: list[ListeningQuestion]


class StartListeningResponse(BaseModel):
    attempt_id: UUID
    started_at: datetime
    server_time: datetime
    status: str
    module: str = "listening"
    duration_seconds: int


class ListeningQuestionsResponse(BaseModel):
    test: TestSummary
    module: str = "listening"
    parts: list[ListeningPart]
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


class SubmitListeningRequest(BaseModel):
    answers: list[SubmitAnswer] = Field(default_factory=list)


class SkillBreakdownEntry(BaseModel):
    correct: int
    total: int
    pct: float


class ListeningScoreReport(BaseModel):
    attempt_id: UUID
    status: str
    submitted_at: datetime | None = None
    raw_score: int
    total_questions: int
    band: float
    late_submission: bool = False
    skill_breakdown: dict[str, SkillBreakdownEntry] = Field(default_factory=dict)


class SubmitListeningResponse(BaseModel):
    attempt_id: UUID
    status: str
    submitted_at: datetime
    raw_score: int
    total_questions: int
    band: float
    late_submission: bool = False
    skill_breakdown: dict[str, SkillBreakdownEntry] = Field(default_factory=dict)
