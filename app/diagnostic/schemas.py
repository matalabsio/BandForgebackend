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
