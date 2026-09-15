"""Pydantic schemas — English Forge §6.2 coach contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


GradeBand = Literal["1-3", "4-5", "6-8", "9-10"]
Understandable = Literal["yes", "mostly", "difficult"]


class PrimaryFix(BaseModel):
    before: str
    after: str
    why_kid_friendly: str


class CoachInternalSignals(BaseModel):
    fluency_note: Optional[str] = None
    grammar_severity: Optional[Literal["none", "minor", "high_impact"]] = None
    pronunciation_advisory: Optional[
        Literal["clear_enough", "some_unclear_words", "hard_to_follow"]
    ] = None
    task_relevance: Optional[Literal["on_topic", "partial", "off_topic"]] = None
    over_correction_risk: Optional[str] = None
    evaluator_version: Optional[str] = None
    rubric_version: Optional[str] = None
    schema_version: Optional[str] = None


class CoachCard(BaseModel):
    understandable: Understandable
    strength: str
    primary_fix: Optional[PrimaryFix] = None
    new_words: list[str] = Field(default_factory=list, max_length=3)
    filler_note: Optional[str] = None
    retry_prompt: str
    internal_signals: Optional[CoachInternalSignals] = None


class SpeakPrompt(BaseModel):
    id: str
    grade_band: GradeBand
    title: str
    prompt: str
    listen_hint: Optional[str] = None
    target_duration_sec: int
    max_duration_sec: int
    reference_transcript: Optional[str] = None
    is_anchor: bool = False
    skills: list[str] = Field(default_factory=list)
    difficulty: Optional[str] = None


class CreateSessionRequest(BaseModel):
    grade_band: GradeBand = "6-8"
    prompt_id: Optional[str] = None
    guest_key: Optional[str] = None


class SessionPublic(BaseModel):
    id: UUID
    grade_band: GradeBand
    prompt: SpeakPrompt
    status: str
    created_at: datetime | str


class CreateResponseSessionRequest(BaseModel):
    content_type: str = "audio/webm"
    duration_sec: int = Field(ge=1, le=180)
    size_bytes: int = Field(ge=500, le=25_000_000)
    idempotency_key: Optional[str] = None


class ResponseSessionPublic(BaseModel):
    response_id: UUID
    upload_url: str
    expires_at: datetime | str
    idempotency_key: str
    stub_upload: bool = False


class ConfirmResponseRequest(BaseModel):
    idempotency_key: str
    duration_sec: int = Field(ge=1, le=180)


class ResponsePublic(BaseModel):
    id: UUID
    session_id: UUID
    status: str
    duration_sec: int
    transcription_status: str


class PendingStatus(BaseModel):
    session_id: UUID
    status: str
    transcription_status: str
    evaluation_status: str
    ready: bool
    message: str


class FeedbackPublic(BaseModel):
    session_id: UUID
    transcript: str
    coach_card: CoachCard
    evaluation_status: str


class EvaluateRequest(BaseModel):
    grade_band: GradeBand
    prompt: str
    transcript: str
    duration_sec: float
    word_timestamps: Optional[list[dict[str, Any]]] = None
    locale_hint: Optional[str] = None
    attempt_meta: Optional[dict[str, Any]] = None


class EvaluateResponse(BaseModel):
    transcript: str
    coach_card: CoachCard
