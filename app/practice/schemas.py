"""Pydantic models for practice hubs API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SkillName = Literal["listening", "reading", "writing", "speaking"]
HubStatus = Literal["pending", "in_progress", "completed"]


class PracticeVideo(BaseModel):
    title: str = ""
    url: str = ""
    duration_min: int = 0


class PracticeHubOut(BaseModel):
    id: str
    slug: str
    skill: SkillName
    bank_number: int
    set_number: int
    title: str
    estimated_min: int = 25
    sort_order: int = 0
    status: HubStatus = "pending"
    completed_at: datetime | None = None


class PracticeHubDetailOut(PracticeHubOut):
    videos: list[PracticeVideo] = Field(default_factory=list)
    practice_prompt: str = ""
    submit_config: dict[str, Any] = Field(default_factory=dict)


class SkillHubProgressOut(BaseModel):
    skill: SkillName
    completed_count: int = 0
    total_count: int = 0
    required_for_mock: int = 12
    mock_unlocked: bool = False
    mock_test_id: str | None = None


class PracticeProgressOut(BaseModel):
    skills: list[SkillHubProgressOut] = Field(default_factory=list)


class MockUnlockOut(BaseModel):
    skill: SkillName
    unlocked: bool
    completed: int
    required: int
    mock_test_id: str | None = None


class HubCompleteOut(BaseModel):
    hub_id: str
    status: HubStatus
    completed_at: datetime | None = None
    skill_progress: SkillHubProgressOut
