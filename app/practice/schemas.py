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
    tag: str | None = None
    stream_uid: str | None = None


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
    accessible: bool = True
    locked_reason: str | None = None


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
    mocks_granted: int | None = None
    mocks_used: int | None = None
    # Writing Skill pack only — Academic / GT from user_program_usage.
    exam_module: Literal["academic", "general_training"] | None = None


class WritingSkillExamModuleRequest(BaseModel):
    exam_module: Literal["academic", "general_training"]


class WritingSkillExamModuleOut(BaseModel):
    exam_module: Literal["academic", "general_training"]
    usage_id: str
    changed: bool = False


class HubCompleteOut(BaseModel):
    hub_id: str
    status: HubStatus
    completed_at: datetime | None = None
    skill_progress: SkillHubProgressOut


class BankExerciseQuestionOut(BaseModel):
    id: str
    question_number: int
    question_type: str
    prompt: str
    options: Any = None
    instructions: str | None = None
    audio_url: str | None = None
    video_url: str | None = None
    correct_answer: str | None = None
    difficulty: str = "medium"


class BankExerciseSectionOut(BaseModel):
    section_id: str
    part: int
    module: SkillName
    title: str | None = None
    instructions: str | None = None
    audio_key: str | None = None
    audio_url: str | None = None
    passage_text: str | None = None
    image_url: str | None = None
    questions: list[BankExerciseQuestionOut] = Field(default_factory=list)


class ExerciseStartOut(BaseModel):
    attempt_id: str
    hub_id: str
    practice_set_id: str
    skill: SkillName
    part: int
    section: BankExerciseSectionOut
    # Speaking bank: linked speaking test_attempt for R2 upload + ASR.
    speaking_attempt_id: str | None = None
    speaking_manifest_hash: str | None = None


class ExerciseSubmitRequest(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)


class ExerciseSubmitOut(BaseModel):
    attempt_id: str
    status: Literal["completed"] = "completed"
    score: dict[str, Any] | None = None
    hub_completed: bool = False
    skill_progress: SkillHubProgressOut | None = None
    # Writing bank exercises: Claude eval queued (v5); poll writing-review.
    writing_ai_pending: bool = False
    writing_part: int | None = None
    # Speaking bank: ASR/LLM eval queued; poll speaking-review.
    speaking_ai_pending: bool = False
    speaking_attempt_id: str | None = None


class PracticeWritingReviewOut(BaseModel):
    """Same shape the student WritingFeedbackView expects (practice hub)."""

    attempt_id: str
    hub_id: str
    status: str
    module: str = "writing"
    part: int
    test_title: str | None = None
    question_type: str = "writing"
    prompt: str = ""
    options: dict[str, Any] | None = None
    user_answer: str = ""
    word_count: int = 0
    band: float | None = None
    ai_band: float | None = None
    ai_available: bool = False
    ai_status: str | None = None
    band_source: str = "none"
    human_verified: bool = False
    reviewer_notes: str | None = None
    ai_criteria: dict[str, float] = Field(default_factory=dict)
    ai_strengths: list[str] = Field(default_factory=list)
    ai_improvements: list[str] = Field(default_factory=list)
    ai_model_name: str | None = None
    ai_provider: str | None = None
    spelling_mistakes: list[Any] = Field(default_factory=list)
    grammar_mistakes: list[Any] = Field(default_factory=list)
    next_band_advice: str = ""
    confidence: float | None = None
    vocabulary_highlights: list[Any] = Field(default_factory=list)
    strong_spans: list[Any] = Field(default_factory=list)
    min_words: int = 150
    submitted_at: str | None = None
    saved_for_review: bool = True
    error: str | None = None
    word_count_estimate: float | None = None


class PracticeSpeakingReviewOut(BaseModel):
    """Provisional AI payload for practice speaking results (hub)."""

    attempt_id: str
    hub_id: str
    speaking_attempt_id: str | None = None
    status: str
    module: str = "speaking"
    test_title: str | None = None
    ai_available: bool = False
    ai_status: str | None = None
    ai_band: float | None = None
    band_source: str = "none"
    ai_criteria: dict[str, float] = Field(default_factory=dict)
    ai_strengths: list[str] = Field(default_factory=list)
    ai_improvements: list[str] = Field(default_factory=list)
    next_band_advice: str | None = None
    ai_parts: list[Any] = Field(default_factory=list)
    ai_evidence: list[Any] = Field(default_factory=list)
    ai_patterns: list[Any] = Field(default_factory=list)
    ai_fluency: dict[str, Any] = Field(default_factory=dict)
    responses: list[Any] = Field(default_factory=list)
    ai_model_name: str | None = None
    ai_provider: str | None = None
    submitted_at: str | None = None
    error: str | None = None
    message: str | None = None
    evaluation_status: str | None = None
