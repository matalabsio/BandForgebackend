"""Pydantic models for admin API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

MockStatus = Literal["draft", "published", "archived"]
UserRole = Literal["student", "admin", "super_admin"]
AdminUserRole = Literal["student", "admin", "super_admin", "guest"]


class DashboardMetrics(BaseModel):
    total_users: int = 0
    active_users_7d: int = 0
    new_signups_7d: int = 0
    mock_attempts_7d: int = 0
    speaking_pending: int = 0
    writing_pending: int = 0
    total_mocks: int = 0
    published_mocks: int = 0
    users_trend_pct: int | None = None
    signups_trend_pct: int | None = None
    mocks_trend_pct: int | None = None


class DailyActivityPoint(BaseModel):
    label: str
    date: str
    active_users: int = 0
    signups: int = 0
    mock_attempts: int = 0


class RecentActivityItem(BaseModel):
    id: str
    message: str
    created_at: datetime
    kind: str = "event"


class DashboardOverview(BaseModel):
    metrics: DashboardMetrics
    weekly_activity: list[DailyActivityPoint] = Field(default_factory=list)
    recent_activity: list[RecentActivityItem] = Field(default_factory=list)


class AdminUserListItem(BaseModel):
    id: UUID
    email: str | None = None
    full_name: str | None = None
    role: AdminUserRole = "student"
    is_active: bool = True
    created_at: datetime
    mock_attempt_count: int = 0
    completed_mock_count: int = 0
    last_activity_at: datetime | None = None
    best_band: float | None = None


class AdminUserListResponse(BaseModel):
    items: list[AdminUserListItem]
    total: int
    page: int
    page_size: int


class AdminUserDetail(BaseModel):
    id: UUID
    email: str | None = None
    full_name: str | None = None
    phone: str | None = None
    role: AdminUserRole = "student"
    is_active: bool = True
    email_verified: bool = False
    created_at: datetime
    mock_attempt_count: int = 0
    completed_mock_count: int = 0
    target_band: float | None = None


class AdminUserAttemptItem(BaseModel):
    id: UUID
    kind: Literal["mock", "module"]
    mock_test_id: UUID | None = None
    mock_title: str | None = None
    module: str | None = None
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    band: float | None = None


class PatchAdminUserRequest(BaseModel):
    is_active: bool | None = None
    role: UserRole | None = None


class AdminUserActivityStats(BaseModel):
    total_attempts: int = 0
    completed_attempts: int = 0
    in_progress_attempts: int = 0
    average_band: float | None = None
    best_band: float | None = None
    last_activity_at: datetime | None = None
    current_streak: int = 0
    longest_streak: int = 0


class AdminUserInProgressItem(BaseModel):
    id: str
    module: str
    started_at: datetime
    mock_test_id: str
    mock_title: str
    catalog_number: int | None = None


class AdminUserModuleAttemptItem(BaseModel):
    id: str
    module: str
    started_at: datetime
    completed_at: datetime | None = None
    status: str
    band: float | None = None
    raw_score: int | None = None
    total_count: int | None = None
    mock_test_id: str
    mock_title: str
    catalog_number: int | None = None


class AdminUserMockSessionItem(BaseModel):
    mock_attempt_id: str
    mock_test_id: str
    mock_title: str | None = None
    catalog_number: int | None = None
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    listening_band: float | None = None
    reading_band: float | None = None
    writing_band: float | None = None
    speaking_band: float | None = None
    aggregate_band: float | None = None


class AdminUserDiagnosticItem(BaseModel):
    id: str
    client_attempt_id: str
    status: str
    listening_band: float | None = None
    reading_band: float | None = None
    writing_band: float | None = None
    speaking_band: float | None = None
    aggregate_band: float | None = None
    review: dict[str, Any] | None = None
    pack_version: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class AdminUserSpeakingReviewItem(BaseModel):
    id: str
    attempt_id: str
    status: str
    human_band: float | None = None
    created_at: datetime
    mock_title: str | None = None


class AdminUserOverview(BaseModel):
    profile: AdminUserDetail
    stats: AdminUserActivityStats
    in_progress: list[AdminUserInProgressItem] = Field(default_factory=list)
    recent_modules: list[AdminUserModuleAttemptItem] = Field(default_factory=list)
    mock_sessions: list[AdminUserMockSessionItem] = Field(default_factory=list)
    diagnostics: list[AdminUserDiagnosticItem] = Field(default_factory=list)
    speaking_reviews: list[AdminUserSpeakingReviewItem] = Field(default_factory=list)


class MockModuleSummary(BaseModel):
    module: str
    sequence_order: int
    duration_minutes: int
    is_enabled: bool
    question_count: int = 0
    parts: list[int] = Field(default_factory=list)


class AdminMockListItem(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    status: MockStatus
    is_published: bool
    is_free: bool = False
    catalog_number: int | None = None
    created_at: datetime
    total_questions: int = 0
    attempt_count: int = 0
    modules: list[MockModuleSummary] = Field(default_factory=list)


class SectionStatus(BaseModel):
    part: int
    question_count: int = 0
    has_audio: bool = False


class ModuleSectionStatus(BaseModel):
    module: str
    sections: list[SectionStatus] = Field(default_factory=list)


class AdminMockDetail(AdminMockListItem):
    configured_listening_parts: int = 4
    configured_reading_passages: int = 3
    configured_writing_tasks: int = 2
    section_status: list[ModuleSectionStatus] = Field(default_factory=list)
    publish_blockers: list[str] = Field(default_factory=list)


class CreateMockRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    catalog_number: int | None = Field(default=None, ge=1, le=20)
    listening_parts: int = Field(default=4, ge=1, le=4)
    reading_passages: int = Field(default=3, ge=1, le=4)
    writing_tasks: int = Field(default=2, ge=1, le=2)


class PatchMockRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    catalog_number: int | None = Field(default=None, ge=1, le=20)
    listening_parts: int | None = Field(default=None, ge=1, le=4)
    reading_passages: int | None = Field(default=None, ge=1, le=4)
    writing_tasks: int | None = Field(default=None, ge=1, le=2)
    is_free: bool | None = None


class PatchMockStatusRequest(BaseModel):
    status: MockStatus


class QuestionTreePart(BaseModel):
    part: int
    question_count: int
    questions: list[QuestionTreeItem] = Field(default_factory=list)


class QuestionTreeItem(BaseModel):
    id: UUID
    question_number: int
    question_type: str
    prompt: str
    part: int | None = None


class QuestionTreeModule(BaseModel):
    module: str
    parts: list[QuestionTreePart] = Field(default_factory=list)


class QuestionTreeResponse(BaseModel):
    mock_test_id: UUID
    modules: list[QuestionTreeModule] = Field(default_factory=list)


class QuestionVersionItem(BaseModel):
    id: UUID
    version: int
    content: dict[str, Any]
    created_at: datetime
    created_by: UUID | None = None


class AdminQuestionDetail(BaseModel):
    id: UUID
    mock_test_id: UUID
    module: str
    part: int | None = None
    question_type: str
    question_number: int
    prompt: str
    passage_text: str | None = None
    options: list[dict[str, Any]] | None = None
    correct_answer: str | None = None
    explanation: str | None = None
    skill_tag: str | None = None
    versions: list[QuestionVersionItem] = Field(default_factory=list)


class PatchQuestionRequest(BaseModel):
    prompt: str | None = None
    options: list[dict[str, Any]] | None = None
    correct_answer: str | None = None
    explanation: str | None = None


class IngestValidateRequest(BaseModel):
    module: Literal["listening", "reading"]
    part: int = Field(ge=1, le=4)
    data: dict[str, Any]
    audio_key: str | None = None


class IngestValidateResponse(BaseModel):
    ok: bool
    question_count: int = 0
    preview: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class IngestPublishRequest(BaseModel):
    module: Literal["listening", "reading"]
    part: int = Field(ge=1, le=4)
    data: dict[str, Any]
    audio_key: str | None = None


class IngestPublishResponse(BaseModel):
    ok: bool
    questions_written: int
    module: str
    part: int


class HumanCriteriaScores(BaseModel):
    fluency: float = Field(ge=0, le=9)
    lexical: float = Field(ge=0, le=9)
    grammar: float = Field(ge=0, le=9)
    pronunciation: float = Field(ge=0, le=9)


class SpeakingAdminEvidence(BaseModel):
    quote: str
    criterion: Literal["FC", "LR", "GRA", "P"]
    polarity: Literal["strength", "weakness"]
    part: int = Field(ge=1, le=3)
    response_id: str | None = None
    question_id: str | None = None
    issue: str | None = None
    title: str | None = None
    explanation: str | None = None
    suggestion: str | None = None
    advisory_only: bool = False
    inference_source: Literal["audio", "transcript_inferred"] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class SpeakingAdminPronunciationAdvisory(BaseModel):
    inference_source: Literal["transcript_inferred"] = "transcript_inferred"
    advisory_only: Literal[True] = True
    confidence: float | None = Field(default=None, ge=0, le=1)
    low_confidence: bool = True
    released_score_authority: Literal["human_examiner"] = "human_examiner"


class SpeakingSubmissionResponseMeta(BaseModel):
    response_id: UUID
    question_id: UUID
    part: int
    sequence_number: int
    duration_sec: int
    audio_url: str
    audio_play_url: str | None = None
    prompt: str | None = None
    status: str | None = None
    confirmed_at: datetime | None = None
    transcription_status: str | None = None
    transcript: str | None = None
    fluency_metrics: dict[str, Any] | None = None
    ai_status: str | None = None
    ai_evidence: list[SpeakingAdminEvidence] = Field(default_factory=list)
    ai_result: dict[str, Any] | None = None


class SpeakingSubmissionMeta(BaseModel):
    part: int | None = None
    part_label: str | None = None
    cue_card: str | None = None
    prompt_title: str | None = None
    manifest_hash: str | None = None
    response_count: int | None = None
    responses: list[SpeakingSubmissionResponseMeta] = Field(default_factory=list)
    parts: list[int] = Field(default_factory=list)


class SpeakingQueueItem(BaseModel):
    id: UUID
    attempt_id: UUID
    student_name: str | None = None
    student_email: str | None = None
    status: str
    human_band: float | None = None
    ai_overall_band: float | None = None
    created_at: datetime


class SpeakingQueueResponse(BaseModel):
    items: list[SpeakingQueueItem]
    total: int
    page: int
    page_size: int
    pending_count: int = 0


class SpeakingReviewDetail(BaseModel):
    id: UUID
    attempt_id: UUID
    status: str
    human_band: float | None = None
    human_criteria_scores: HumanCriteriaScores | None = None
    submission_meta: SpeakingSubmissionMeta | None = None
    reviewer_notes: str | None = None
    transcript: str | None = None
    audio_url: str | None = None
    audio_play_url: str | None = None
    ai_scores: dict[str, Any] | None = None
    part_metrics: dict[str, Any] = Field(default_factory=dict)
    attempt_metrics: dict[str, Any] | None = None
    response_metrics: list[dict[str, Any]] = Field(default_factory=list)
    transcription_progress: dict[str, int] | None = None
    ai_status: str | None = None
    ai_evidence: list[SpeakingAdminEvidence] = Field(default_factory=list)
    ai_pronunciation_advisory: SpeakingAdminPronunciationAdvisory | None = None
    evaluation_status: str | None = None
    evaluation_error: str | None = None
    approval_version: int = 0
    reopened_at: datetime | None = None
    student_name: str | None = None
    student_email: str | None = None
    student_target_band: float | None = None
    student_current_band: float | None = None
    queue_pending_count: int = 0
    created_at: datetime
    reviewed_at: datetime | None = None


class PatchSpeakingReviewRequest(BaseModel):
    human_criteria_scores: HumanCriteriaScores | None = None
    reviewer_notes: str | None = None
    status: Literal["in_review"] | None = None


class ApproveSpeakingRequest(BaseModel):
    human_criteria_scores: HumanCriteriaScores
    reviewer_notes: str | None = None
    audio_confirmed: bool
    confirmation: Literal["confirm_final_approval"]
    idempotency_key: str = Field(min_length=16, max_length=128)
    ai_override_note: str | None = Field(default=None, max_length=2000)


class ReopenSpeakingReviewRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


class WritingHumanCriteriaScores(BaseModel):
    task_achievement: float = Field(ge=0, le=9)
    coherence: float = Field(ge=0, le=9)
    lexical_resource: float = Field(ge=0, le=9)
    grammar: float = Field(ge=0, le=9)


class WritingSubmissionMeta(BaseModel):
    part: int | None = None
    part_label: str | None = None
    prompt_title: str | None = None
    question: str | None = None
    essay: str | None = None
    word_count: int | None = None
    mock_title: str | None = None


class WritingQueueItem(BaseModel):
    id: UUID
    source: Literal["mock", "diagnostic"]
    student_name: str | None = None
    student_email: str | None = None
    status: str
    human_band: float | None = None
    ai_overall_band: float | None = None
    ai_status: str | None = None
    task_label: str | None = None
    created_at: datetime


class WritingQueueResponse(BaseModel):
    items: list[WritingQueueItem]
    total: int
    page: int
    page_size: int
    pending_count: int = 0


class WritingReviewDetail(BaseModel):
    id: UUID
    source: Literal["mock", "diagnostic"]
    attempt_id: UUID | None = None
    client_attempt_id: str | None = None
    status: str
    human_band: float | None = None
    human_criteria_scores: WritingHumanCriteriaScores | None = None
    submission_meta: WritingSubmissionMeta | None = None
    essay: str | None = None
    question: str | None = None
    word_count: int | None = None
    reviewer_notes: str | None = None
    ai_scores: dict[str, Any] | None = None
    ai_feedback: dict[str, Any] | None = None
    ai_status: str | None = None
    ai_error: str | None = None
    student_name: str | None = None
    student_email: str | None = None
    student_target_band: float | None = None
    student_current_band: float | None = None
    task_label: str | None = None
    mock_title: str | None = None
    queue_pending_count: int = 0
    created_at: datetime
    reviewed_at: datetime | None = None


class PatchWritingReviewRequest(BaseModel):
    human_criteria_scores: WritingHumanCriteriaScores | None = None
    reviewer_notes: str | None = None
    status: Literal["in_review"] | None = None


class ApproveWritingRequest(BaseModel):
    human_criteria_scores: WritingHumanCriteriaScores
    reviewer_notes: str | None = None


class AuditLogItem(BaseModel):
    id: UUID
    admin_id: UUID
    admin_email: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime


class AuditLogResponse(BaseModel):
    items: list[AuditLogItem]
    total: int
    page: int
    page_size: int


class ReviewHistoryItem(BaseModel):
    id: UUID
    action: str
    admin_email: str | None = None
    summary: str
    metadata: dict[str, Any] | None = None
    created_at: datetime


class ReviewHistoryResponse(BaseModel):
    items: list[ReviewHistoryItem]


class CriterionMaeItem(BaseModel):
    key: str
    label: str
    mae: float | None = None
    sample_count: int = 0


class ReviewAnalyticsResponse(BaseModel):
    module: str
    days: int
    completed: int
    with_ai: int
    without_ai: int
    agreement_rate: float | None = None
    override_rate: float | None = None
    overall_mae: float | None = None
    criterion_mae: list[CriterionMaeItem] = Field(default_factory=list)


class DiagnosticSpeakingPart1Item(BaseModel):
    question_id: str
    duration_sec: int = 0
    completed: bool = False


class DiagnosticSpeakingSummary(BaseModel):
    part1: list[DiagnosticSpeakingPart1Item] = Field(default_factory=list)
    part2_prep_sec: int | None = None
    part2_record_sec: int | None = None
    part2_completed: bool = False


class DiagnosticQueueItem(BaseModel):
    id: UUID
    full_name: str
    email: str | None = None
    phone: str
    goal_label: str | None = None
    target_band: float | None = None
    listening_band: float | None = None
    reading_band: float | None = None
    writing_band: float | None = None
    speaking_band: float | None = None
    speaking_human_band: float | None = None
    aggregate_band: float | None = None
    status: str
    report_email_sent_at: datetime | None = None
    created_at: datetime


class DiagnosticQueueResponse(BaseModel):
    items: list[DiagnosticQueueItem]
    total: int
    page: int
    page_size: int
    pending_count: int = 0


class DiagnosticWritingSummary(BaseModel):
    task_part: int | None = None
    overall_band: float | None = None
    essay_preview: str | None = None
    word_count: int | None = None
    ai_feedback: dict[str, Any] | None = None


class DiagnosticDetail(BaseModel):
    id: UUID
    client_attempt_id: str
    full_name: str
    email: str | None = None
    phone: str
    goal_label: str | None = None
    target_band: float | None = None
    listening_band: float | None = None
    reading_band: float | None = None
    writing_band: float | None = None
    writing_human_band: float | None = None
    speaking_band: float | None = None
    speaking_human_band: float | None = None
    aggregate_band: float | None = None
    status: str
    speaking_human_criteria_scores: HumanCriteriaScores | None = None
    speaking_reviewer_notes: str | None = None
    speaking_reviewed_at: datetime | None = None
    report_email_sent_at: datetime | None = None
    writing_review_id: UUID | None = None
    writing: DiagnosticWritingSummary | None = None
    speaking: DiagnosticSpeakingSummary | None = None
    created_at: datetime
    reviewed_at: datetime | None = None


class PatchDiagnosticSpeakingRequest(BaseModel):
    human_criteria_scores: HumanCriteriaScores
    reviewer_notes: str | None = None


class SendDiagnosticReportResponse(BaseModel):
    ok: bool
    sent_at: datetime
    recipient: str
