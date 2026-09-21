"""Pydantic models for intern screening APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.diagnostic.evaluation_schemas import (
    DiagnosticEvaluateWritingFailedResponse,
    DiagnosticEvaluateWritingPendingResponse,
    DiagnosticEvaluateWritingResponse,
)

InternRole = Literal["frontend", "backend", "fullstack", "product", "other"]
InternStatus = Literal["in_progress", "processing", "completed"]
InternModule = Literal["listening", "reading", "writing", "speaking"]


class InternCreateRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str = Field(default="", max_length=32)
    college: str = Field(default="", max_length=160)
    role_applied: InternRole = "fullstack"


class InternApplicationPublic(BaseModel):
    id: UUID
    access_token: str
    full_name: str
    email: str
    phone: str
    college: str
    role_applied: str
    status: InternStatus
    current_module: InternModule
    listening_band: float | None = None
    reading_band: float | None = None
    writing_band: float | None = None
    speaking_band: float | None = None
    aggregate_band: float | None = None
    writing_evaluation: dict[str, Any] | None = None
    speaking_evaluation: dict[str, Any] | None = None
    writing_eval_pending: bool = False
    writing_eval_essay_hash: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class InternProgressRequest(BaseModel):
    current_module: InternModule
    answers: dict[str, Any] | None = None
    listening_band: float | None = Field(default=None, ge=0, le=9)
    reading_band: float | None = Field(default=None, ge=0, le=9)
    review: dict[str, Any] | None = None
    pack_version: str | None = None


class InternCompleteRequest(BaseModel):
    listening_band: float | None = Field(default=None, ge=0, le=9)
    reading_band: float | None = Field(default=None, ge=0, le=9)
    writing_band: float | None = Field(default=None, ge=0, le=9)
    speaking_band: float | None = Field(default=None, ge=0, le=9)
    aggregate_band: float | None = Field(default=None, ge=0, le=9)
    review: dict[str, Any] | None = None
    answers: dict[str, Any] | None = None
    pack_version: str | None = None


class InternSpeakingClipMeta(BaseModel):
    question_id: str = Field(min_length=1, max_length=128)
    part: int = Field(ge=1, le=3)
    duration_sec: float = Field(ge=0, le=300)
    prompt: str = Field(default="", max_length=4000)


class InternSpeakingMeta(BaseModel):
    recordings: list[InternSpeakingClipMeta] = Field(min_length=1, max_length=12)


class InternSpeakingEvalResponse(BaseModel):
    speaking_band: float | None
    provider: str
    asr_provider: str
    status: Literal["complete", "insufficient_speech"]
    transcripts: list[dict[str, Any]]
    evaluation: dict[str, Any]


class InternAdminListItem(BaseModel):
    id: UUID
    full_name: str
    email: str
    college: str
    role_applied: str
    status: InternStatus
    listening_band: float | None = None
    reading_band: float | None = None
    writing_band: float | None = None
    speaking_band: float | None = None
    aggregate_band: float | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class InternAdminListResponse(BaseModel):
    items: list[InternAdminListItem]
    total: int
    page: int
    page_size: int


InternWritingStartResponse = (
    DiagnosticEvaluateWritingResponse | DiagnosticEvaluateWritingPendingResponse
)
InternWritingStatusResponse = (
    DiagnosticEvaluateWritingResponse
    | DiagnosticEvaluateWritingPendingResponse
    | DiagnosticEvaluateWritingFailedResponse
)
