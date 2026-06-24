"""Diagnostic API request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DiagnosticCompleteRequest(BaseModel):
    client_attempt_id: str = Field(min_length=1, max_length=128)
    listening_band: float | None = None
    reading_band: float | None = None
    writing_band: float | None = None
    speaking_band: float | None = None
    aggregate_band: float | None = None
    review: dict[str, Any] | None = None
    pack_version: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class DiagnosticCompleteResponse(BaseModel):
    id: str
    client_attempt_id: str
    status: str = "completed"


class DiagnosticReviewSubmitRequest(BaseModel):
    client_attempt_id: str = Field(min_length=1, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=10, max_length=20)
    email: str | None = Field(default=None, max_length=320)
    goal_label: str | None = None
    target_band: float | None = None
    listening_band: float | None = None
    reading_band: float | None = None
    writing_band: float | None = None
    speaking_band: float | None = None
    aggregate_band: float | None = None
    answers: dict[str, Any] = Field(default_factory=dict)
    review: dict[str, Any] | None = None


class DiagnosticReviewSubmitResponse(BaseModel):
    id: str
    client_attempt_id: str
    status: str = "pending_review"
