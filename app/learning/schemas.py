"""Pydantic models for adaptive learning profiles and study plans."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ModuleBandSummary(BaseModel):
    latest: float | None = None
    best: float | None = None
    n: int = 0
    gap: float | None = None


class WeaknessItem(BaseModel):
    area: str
    module: str
    label: str
    severity: float = Field(ge=0, le=1, description="0=mild, 1=severe")
    evidence_count: int = 0


class RecommendationItem(BaseModel):
    id: str
    title: str
    reason: str
    href: str
    module: str | None = None


class WeeklyGoal(BaseModel):
    id: str
    title: str
    module: str | None = None
    done: bool = False


class StudyTask(BaseModel):
    id: str
    title: str
    subtitle: str = ""
    module: str
    kind: Literal["practice", "homework", "goal"] = "practice"
    task_type: Literal["watch", "practice", "submit"] = "practice"
    hub_id: str | None = None
    duration_min: int = 20
    href: str = "/dashboard"
    status: Literal["pending", "done", "skipped"] = "pending"


class StudyDay(BaseModel):
    date: str  # YYYY-MM-DD
    label: str
    tasks: list[StudyTask] = Field(default_factory=list)


class StudyWeek(BaseModel):
    id: str
    label: str
    focus: str = ""
    days: list[StudyDay] = Field(default_factory=list)


class StudyPlan(BaseModel):
    weekly_focus: str = ""
    weeks: list[StudyWeek] = Field(default_factory=list)
    prep_start: date | None = None
    exam_date: date | None = None
    total_days: int | None = None
    plan_tier: str | None = None
    skill_difficulty: dict[str, str] = Field(default_factory=dict)
    session_path_kind: str | None = None
    diagnostic_attempt_id: str | None = None
    assigned_hub_ids: list[str] = Field(default_factory=list)


class VocabStats(BaseModel):
    highlight_count: int = 0
    weak_count: int = 0
    strong_count: int = 0
    recurring_weak: list[str] = Field(default_factory=list)
    growth_delta: int = 0


class GrammarStats(BaseModel):
    mistake_count: int = 0
    by_issue: dict[str, int] = Field(default_factory=dict)
    top_issues: list[str] = Field(default_factory=list)


class SourceCounts(BaseModel):
    listening: int = 0
    reading: int = 0
    writing: int = 0
    speaking: int = 0
    diagnostic: int = 0


class SkillHubProgress(BaseModel):
    skill: str
    completed_count: int = 0
    total_count: int = 0
    required_for_mock: int = 12
    mock_unlocked: bool = False
    mock_test_id: str | None = None


class WeeklyHubCompletion(BaseModel):
    date: str  # YYYY-MM-DD (local calendar day of completion)
    skill: str
    hub_id: str


class LearningProfileResponse(BaseModel):
    user_id: str
    current_band: float | None = None
    target_band: float | None = None
    gap_to_target: float | None = None
    module_summary: dict[str, ModuleBandSummary] = Field(default_factory=dict)
    criterion_trends: dict[str, Any] = Field(default_factory=dict)
    skill_weaknesses: list[dict[str, Any]] = Field(default_factory=list)
    top_weaknesses: list[WeaknessItem] = Field(default_factory=list)
    vocab_stats: VocabStats = Field(default_factory=VocabStats)
    grammar_stats: GrammarStats = Field(default_factory=GrammarStats)
    recommendations: list[RecommendationItem] = Field(default_factory=list)
    study_plan: StudyPlan = Field(default_factory=StudyPlan)
    weekly_goals: list[WeeklyGoal] = Field(default_factory=list)
    source_counts: SourceCounts = Field(default_factory=SourceCounts)
    refreshed_at: datetime | None = None
    plan_week_start: date | None = None
    todays_tasks: list[StudyTask] = Field(default_factory=list)
    prep_start: date | None = None
    exam_date: date | None = None
    total_days: int | None = None
    current_day: int | None = None
    days_remaining: int | None = None
    skill_difficulty: dict[str, str] = Field(default_factory=dict)
    hub_progress: dict[str, SkillHubProgress] = Field(default_factory=dict)
    weekly_hub_completions: list[WeeklyHubCompletion] = Field(default_factory=list)


class TaskStatusUpdate(BaseModel):
    status: Literal["pending", "done", "skipped"]


class TaskStatusResponse(BaseModel):
    task_id: str
    status: Literal["pending", "done", "skipped"]
    study_plan: StudyPlan


class GeneratePlanRequest(BaseModel):
    plan_tier: str = "full_skill_program"


class TodayBundleResponse(BaseModel):
    """Slim Today payload (Phase 4) — no full study_plan.weeks."""

    user_id: str
    todays_tasks: list[StudyTask] = Field(default_factory=list)
    hub_progress: dict[str, SkillHubProgress] = Field(default_factory=dict)
    prep_start: date | None = None
    exam_date: date | None = None
    total_days: int | None = None
    current_day: int | None = None
    days_remaining: int | None = None
    skill_difficulty: dict[str, str] = Field(default_factory=dict)
    current_band: float | None = None
    target_band: float | None = None
    gap_to_target: float | None = None
