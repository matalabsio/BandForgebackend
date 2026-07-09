"""Pydantic models for the Speaking module API."""

from __future__ import annotations

from datetime import datetime
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
