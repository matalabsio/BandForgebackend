"""Pydantic models for diagnostic AI writing evaluation."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def _round_band(value: float) -> float:
    clamped = max(0.0, min(9.0, float(value)))
    return round(clamped * 2) / 2


class EvaluationResponse(BaseModel):
    """Strict schema for Groq JSON output — validated before persisting."""

    overall_band: float
    task_achievement: float
    coherence: float
    lexical_resource: float
    grammar: float
    strengths: list[str] = Field(min_length=1, max_length=5)
    weaknesses: list[str] = Field(min_length=1, max_length=5)
    improvement_tips: list[str] = Field(min_length=1, max_length=5)

    @field_validator(
        "overall_band",
        "task_achievement",
        "coherence",
        "lexical_resource",
        "grammar",
    )
    @classmethod
    def validate_band(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("Band must be a finite number")
        rounded = _round_band(v)
        if rounded < 0 or rounded > 9:
            raise ValueError("Band must be between 0 and 9")
        return rounded

    @field_validator("strengths", "weaknesses", "improvement_tips")
    @classmethod
    def strip_non_empty_strings(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v if s and s.strip()]
        if not cleaned:
            raise ValueError("List must contain at least one non-empty string")
        return cleaned[:5]


class DiagnosticEvaluateWritingRequest(BaseModel):
    client_attempt_id: str = Field(min_length=1, max_length=128)
    task_part: int = Field(default=1, ge=1, le=2)
    question: str = Field(min_length=1, max_length=8000)
    essay: str = Field(min_length=1, max_length=50000)


class WritingCriterionScores(BaseModel):
    task_achievement: float
    coherence: float
    lexical_resource: float
    grammar: float


class WritingFeedback(BaseModel):
    strengths: list[str]
    weaknesses: list[str]
    improvement_tips: list[str]


class WritingEvaluationMetadata(BaseModel):
    word_count: int
    sentence_count: int
    paragraph_count: int


class DiagnosticEvaluateWritingResponse(BaseModel):
    status: Literal["success"] = "success"
    evaluation_id: str
    writing_band: float
    scores: WritingCriterionScores
    feedback: WritingFeedback
    metadata: WritingEvaluationMetadata
    warnings: list[str] = Field(default_factory=list)


def length_warnings(*, task_part: int, word_count: int) -> list[str]:
    """User-visible warnings when essay is below IELTS recommended length."""
    from app.writing.evaluation import min_words_for_part

    minimum = min_words_for_part(task_part)
    if word_count >= minimum:
        return []
    task_label = f"Task {task_part}"
    return [
        (
            f"Your response was evaluated, but it is substantially below the recommended "
            f"IELTS {task_label} length of {minimum} words. This is likely to reduce your score."
        ),
    ]


def compute_overall_band_from_criteria(
    task_achievement: float,
    coherence: float,
    lexical_resource: float,
    grammar: float,
) -> float:
    """IELTS-style overall: average of four criteria, rounded to nearest 0.5."""
    return _round_band((task_achievement + coherence + lexical_resource + grammar) / 4)


OVERALL_BAND_DRIFT_THRESHOLD = 0.5


def reconcile_overall_band(ev: EvaluationResponse) -> tuple[EvaluationResponse, bool]:
    """Overwrite overall_band when AI value drifts >0.5 from criteria average."""
    calculated = compute_overall_band_from_criteria(
        ev.task_achievement,
        ev.coherence,
        ev.lexical_resource,
        ev.grammar,
    )
    if abs(ev.overall_band - calculated) <= OVERALL_BAND_DRIFT_THRESHOLD:
        return ev, False
    return ev.model_copy(update={"overall_band": calculated}), True


def criteria_from_evaluation(ev: EvaluationResponse) -> dict[str, float]:
    return {
        "task_achievement": ev.task_achievement,
        "coherence": ev.coherence,
        "lexical_resource": ev.lexical_resource,
        "grammar": ev.grammar,
    }


def feedback_from_evaluation(ev: EvaluationResponse) -> dict[str, list[str]]:
    return {
        "strengths": ev.strengths,
        "weaknesses": ev.weaknesses,
        "improvement_tips": ev.improvement_tips,
    }


def row_to_public_response(row: dict[str, Any]) -> DiagnosticEvaluateWritingResponse:
    criteria = row.get("criteria_scores") or {}
    feedback = row.get("feedback") or {}
    words = int(row.get("word_count") or 0)
    task_part = int(row.get("task_part") or 1)
    return DiagnosticEvaluateWritingResponse(
        evaluation_id=str(row["id"]),
        writing_band=float(row["overall_band"]),
        scores=WritingCriterionScores(
            task_achievement=float(criteria.get("task_achievement", 0)),
            coherence=float(criteria.get("coherence", 0)),
            lexical_resource=float(criteria.get("lexical_resource", 0)),
            grammar=float(criteria.get("grammar", 0)),
        ),
        feedback=WritingFeedback(
            strengths=list(feedback.get("strengths") or []),
            weaknesses=list(feedback.get("weaknesses") or []),
            improvement_tips=list(feedback.get("improvement_tips") or []),
        ),
        metadata=WritingEvaluationMetadata(
            word_count=words,
            sentence_count=int(row.get("sentence_count") or 0),
            paragraph_count=int(row.get("paragraph_count") or 0),
        ),
        warnings=length_warnings(task_part=task_part, word_count=words),
    )
