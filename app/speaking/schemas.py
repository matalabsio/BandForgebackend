"""Pydantic models for the Speaking module API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.test_engine import TestSummary


class NotificationPreferencesResponse(BaseModel):
    email_enabled: bool
    plan_reminders_email: bool = True
    whatsapp_enabled: bool
    whatsapp_eligible: bool
    masked_phone: str | None = None
    consent_version: str | None = None


class PatchNotificationPreferencesRequest(BaseModel):
    email_enabled: bool | None = None
    plan_reminders_email: bool | None = None
    whatsapp_enabled: bool | None = None
    consent_confirmation: str | None = Field(default=None, max_length=80)


class SpeakingQuestionPublic(BaseModel):
    id: UUID
    question_number: int
    question_type: str
    prompt: str
    part: int
    sequence_number: int = 1
    kind: str = "question"
    prep_sec: int | None = None
    record_sec: int | None = None
    max_record_sec: int | None = None
    prep_seconds: int = 0
    max_recording_seconds: int = 3600
    duration_hint_sec: int | None = None
    part_label: str | None = None
    video_url: str | None = None


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
    questions: list[SpeakingQuestionPublic] = Field(default_factory=list)
    manifest_hash: str | None = None
    expected_response_count: int = 1
    student_name: str | None = None


class SpeakingEligibilityResponse(BaseModel):
    eligible: bool
    reason: str | None = None
    mock_test_id: UUID
    mock_attempt_id: UUID | None = None


class SpeakingResponsePublic(BaseModel):
    id: UUID
    attempt_id: UUID
    question_id: UUID
    part: int
    sequence_number: int
    duration_sec: int | None = None
    size_bytes: int | None = None
    content_type: str
    status: str
    created_at: datetime
    confirmed_at: datetime | None = None
    expires_at: datetime | None = None
    idempotency_key: str | None = None
    idempotent_replay: bool = False
    transcription_status: str = "not_queued"
    transcription_attempts: int = 0
    transcription_error: str | None = None


class CreateSpeakingResponseSessionRequest(BaseModel):
    question_id: UUID
    part: int = Field(ge=1, le=3)
    sequence_number: int = Field(ge=1)
    duration_sec: int = Field(ge=5)
    size_bytes: int = Field(ge=2000, le=25 * 1024 * 1024)
    content_type: str = Field(min_length=1, max_length=100)
    idempotency_key: str | None = Field(default=None, min_length=16, max_length=128)


class SpeakingResponseSession(BaseModel):
    response_id: UUID
    upload_url: str
    expires_at: datetime
    idempotency_key: str
    idempotent_replay: bool = False


class ConfirmSpeakingResponseRequest(BaseModel):
    idempotency_key: str = Field(min_length=16, max_length=128)
    duration_sec: int = Field(ge=5)


class FinalizeSpeakingRequest(BaseModel):
    manifest_hash: str = Field(min_length=64, max_length=64)


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


ReleaseState = Literal["processing", "awaiting_examiner", "released", "withdrawn"]


class SpeakingReviewerPublic(BaseModel):
    display_name: str
    credential_label: str


class SpeakingReleaseMetadata(BaseModel):
    release_state: ReleaseState
    report_available: bool
    released_at: datetime | None = None
    approval_version: int = 0
    reviewer: SpeakingReviewerPublic | None = None


class SpeakingPendingTranscriptResponse(BaseModel):
    """Owner-visible transcript for one confirmed response."""

    id: UUID
    question_id: UUID
    part: int = Field(ge=1, le=3)
    sequence: int = Field(ge=1)
    prompt: str
    duration_sec: int = Field(ge=0)
    transcription_status: str
    transcript: str
    transcription_error: str | None = None


class SpeakingPendingResponse(BaseModel):
    attempt_id: UUID
    status: str
    review_status: str
    human_band: float | None = None
    ai_status: str | None = None
    evaluation_status: str | None = None
    score_source: Literal[
        "human",
        "ai_estimate",
        "processing",
        "failed",
        "unavailable",
        "insufficient_speech",
    ] = "processing"
    ai_band: float | None = Field(default=None, ge=0, le=9)
    ai_criteria: dict[str, float] = Field(default_factory=dict)
    ai_strengths: list[str] = Field(default_factory=list)
    ai_improvements: list[str] = Field(default_factory=list)
    next_band_advice: str | None = None
    ai_parts: list[dict[str, Any]] = Field(default_factory=list)
    ai_evidence: list[dict[str, Any]] = Field(default_factory=list)
    ai_patterns: list[dict[str, Any]] = Field(default_factory=list)
    ai_fluency: dict[str, Any] = Field(default_factory=dict)
    ai_part_metrics: dict[str, Any] = Field(default_factory=dict)
    responses: list[SpeakingPendingTranscriptResponse] = Field(default_factory=list)
    submitted_at: datetime | None = None
    student_name: str | None = None
    message: str
    transcription_progress: SpeakingTranscriptionProgress | None = None
    release_state: ReleaseState
    report_available: bool
    released_at: datetime | None = None
    approval_version: int = 0
    reviewer: SpeakingReviewerPublic | None = None


class SpeakingHumanCriteria(BaseModel):
    fluency: float
    lexical: float
    grammar: float
    pronunciation: float


class SpeakingFluencyMetrics(BaseModel):
    words_per_minute: float | None = None
    total_speaking_seconds: float | None = None
    long_pauses: int | None = None
    response_count: int | None = None
    questions_asked: int | None = None
    word_count: int | None = None


class SpeakingTranscriptionProgress(BaseModel):
    total: int = 0
    queued: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0


class SpeakingResponseMetrics(SpeakingFluencyMetrics):
    response_id: UUID
    part: int
    sequence_number: int


class SpeakingReportFluency(BaseModel):
    """Canonical deterministic fluency metrics for the released attempt."""

    overall: SpeakingFluencyMetrics | None = None
    parts: dict[str, SpeakingFluencyMetrics] = Field(default_factory=dict)
    responses: list[SpeakingResponseMetrics] = Field(default_factory=list)
    source: Literal["response_metrics", "evaluation_snapshot", "unavailable"]
    complete: bool = False


class SpeakingPauseMarker(BaseModel):
    after_word: str
    gap_sec: float


SpeakingCriterion = Literal["fluency", "lexical", "grammar", "pronunciation"]
SpeakingAnalysisStatus = Literal["complete", "degraded", "unavailable"]


class SpeakingReportAttempt(BaseModel):
    id: UUID
    mock_test_id: UUID | None = None
    mock_attempt_id: UUID | None = None
    mock_title: str | None = None
    test_number: int | None = None
    submitted_at: datetime | None = None


class SpeakingReportStudent(BaseModel):
    display_name: str | None = None
    target_band_at_release: float | None = Field(default=None, ge=0, le=9)


class SpeakingReportRelease(BaseModel):
    released_at: datetime
    approval_version: int = Field(ge=1)
    human_verified: Literal[True] = True
    reviewer: SpeakingReviewerPublic | None = None


class SpeakingCriterionResult(BaseModel):
    band: float = Field(ge=0, le=9)
    target_band: float | None = Field(default=None, ge=0, le=9)
    target_gap: float | None = None


class SpeakingBiggestGap(BaseModel):
    criterion: SpeakingCriterion
    gap: float


class SpeakingReportScores(BaseModel):
    overall: float = Field(ge=0, le=9)
    criteria: dict[SpeakingCriterion, SpeakingCriterionResult]
    biggest_gap: SpeakingBiggestGap | None = None


class SpeakingTranscriptWord(BaseModel):
    text: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)


class SpeakingResponsePause(BaseModel):
    after_word_index: int = Field(ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    duration_ms: int = Field(ge=0)


class SpeakingReportResponseItem(BaseModel):
    id: UUID
    question_id: UUID
    part: int = Field(ge=1, le=3)
    sequence: int = Field(ge=1)
    prompt: str
    duration_sec: int = Field(ge=0)
    transcript: str
    transcript_words: list[SpeakingTranscriptWord] = Field(default_factory=list)
    pause_markers: list[SpeakingResponsePause] = Field(default_factory=list)
    audio_url: str | None = None
    audio_expires_at: datetime | None = None
    metrics: SpeakingFluencyMetrics | None = None


class SpeakingReportPart(BaseModel):
    part: int = Field(ge=1, le=3)
    label: str
    ai_band: float | None = Field(default=None, ge=0, le=9)
    ai_note: str | None = None
    metrics: SpeakingFluencyMetrics | None = None
    response_ids: list[UUID] = Field(default_factory=list)


class SpeakingEvidenceSpan(BaseModel):
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)


class SpeakingReportEvidence(BaseModel):
    response_id: UUID
    question_id: UUID
    part: int = Field(ge=1, le=3)
    criterion: Literal["FC", "LR", "GRA", "P"]
    polarity: Literal["strength", "weakness"]
    quote: str
    issue: str
    title: str
    explanation: str
    suggestion: str
    span: SpeakingEvidenceSpan | None = None
    advisory_only: bool = False
    inference_source: Literal["audio", "transcript_inferred"] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class SpeakingPatternExample(BaseModel):
    text: str
    response_id: UUID | None = None


class SpeakingReportPattern(BaseModel):
    pattern: str
    criterion: Literal["FC", "LR", "GRA", "P"]
    frequency: Literal["rare", "sometimes", "often"]
    occurrence_count: int | None = Field(default=None, ge=0)
    occurrence_count_semantics: Literal["grounded_example_matches"] | None = None
    frequency_is_model_estimate: bool = True
    examples: list[SpeakingPatternExample] = Field(default_factory=list)


class SpeakingPronunciationAdvisory(BaseModel):
    score_authority: Literal["human_examiner"] = "human_examiner"
    ai_inference_source: Literal["transcript_inferred"] = "transcript_inferred"
    ai_advisory_only: Literal[True] = True
    ai_confidence: float | None = Field(default=None, ge=0, le=1)
    ai_low_confidence: bool = True


class SpeakingReportSummary(BaseModel):
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    vocabulary: list[str] = Field(default_factory=list)
    next_advice: str | None = None
    examiner_note: str | None = None


class SpeakingReportAnalysis(BaseModel):
    status: SpeakingAnalysisStatus
    unavailable_sections: list[str] = Field(default_factory=list)


class SpeakingReportResponse(BaseModel):
    """Human-released student speaking report (rich AI + human criteria)."""

    schema_version: Literal["speaking-report.v2"] = "speaking-report.v2"
    attempt: SpeakingReportAttempt
    student: SpeakingReportStudent
    release: SpeakingReportRelease
    scores: SpeakingReportScores
    parts: list[SpeakingReportPart]
    responses: list[SpeakingReportResponseItem]
    fluency_summary: SpeakingReportFluency
    pronunciation_advisory: SpeakingPronunciationAdvisory
    evidence: list[SpeakingReportEvidence] = Field(default_factory=list)
    patterns: list[SpeakingReportPattern] = Field(default_factory=list)
    summary: SpeakingReportSummary
    analysis: SpeakingReportAnalysis

    # Privacy-safe compatibility fields for the current frontend.
    attempt_id: UUID
    status: str
    review_status: str
    overall_band: float
    human_verified: bool = True
    human_criteria_scores: SpeakingHumanCriteria | None = None
    ai_band: float | None = None
    fluency: float | None = None
    lexical: float | None = None
    grammar: float | None = None
    pronunciation: float | None = None
    evaluation: dict[str, Any] | None = None
    fluency_metrics: SpeakingFluencyMetrics | None = None
    attempt_metrics: SpeakingFluencyMetrics | None = None
    part_metrics: dict[str, SpeakingFluencyMetrics] = Field(default_factory=dict)
    response_metrics: list[SpeakingResponseMetrics] = Field(default_factory=list)
    transcription_progress: SpeakingTranscriptionProgress | None = None
    pause_markers: list[SpeakingPauseMarker] = Field(default_factory=list)
    transcript: str | None = None
    audio_play_url: str | None = None
    ai_status: str | None = None
    submitted_at: datetime | None = None
    student_name: str | None = None
    reviewer_notes: str | None = None
    part: int = 1
    release_state: ReleaseState
    report_available: bool
    released_at: datetime | None = None
    approval_version: int = 0
    reviewer: SpeakingReviewerPublic | None = None

