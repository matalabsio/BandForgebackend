"""Pydantic models for diagnostic AI writing evaluation."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def _round_band(value: float) -> float:
    clamped = max(0.0, min(9.0, float(value)))
    return round(clamped * 2) / 2


class SpellingMistake(BaseModel):
    original: str
    correction: str
    context: str = ""


class GrammarMistake(BaseModel):
    original: str
    correction: str
    issue: str = ""


class VocabularyHighlight(BaseModel):
    word: str
    polarity: Literal["strong", "weak"] = "weak"
    alternatives: list[str] = Field(default_factory=list)

    @field_validator("word")
    @classmethod
    def strip_word(cls, v: str) -> str:
        cleaned = (v or "").strip()
        if not cleaned:
            raise ValueError("word must be non-empty")
        return cleaned

    @field_validator("alternatives")
    @classmethod
    def clean_alternatives(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v if s and str(s).strip()][:3]


class StrongSpan(BaseModel):
    text: str
    reason: str = ""

    @field_validator("text")
    @classmethod
    def strip_text(cls, v: str) -> str:
        cleaned = (v or "").strip()
        if not cleaned:
            raise ValueError("text must be non-empty")
        return cleaned

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, v: str) -> str:
        return (v or "").strip()


class EvaluationResponse(BaseModel):
    """Strict schema for LLM JSON output — validated before persisting."""

    overall_band: float
    task_achievement: float
    coherence: float
    lexical_resource: float
    grammar: float
    strengths: list[str] = Field(min_length=1, max_length=5)
    weaknesses: list[str] = Field(min_length=1, max_length=5)
    improvement_tips: list[str] = Field(min_length=1, max_length=5)
    spelling_mistakes: list[SpellingMistake] = Field(default_factory=list)
    grammar_mistakes: list[GrammarMistake] = Field(default_factory=list)
    spelling_error_count: int = 0
    next_band_advice: str = ""
    confidence: float = 0.5
    vocabulary_highlights: list[VocabularyHighlight] = Field(default_factory=list)
    strong_spans: list[StrongSpan] = Field(default_factory=list)

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

    @field_validator("spelling_error_count")
    @classmethod
    def non_negative_spelling_count(cls, v: int) -> int:
        return max(0, int(v))

    @field_validator("next_band_advice")
    @classmethod
    def strip_next_band_advice(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        try:
            value = float(v)
        except (TypeError, ValueError):
            return 0.5
        if not math.isfinite(value):
            return 0.5
        return max(0.0, min(1.0, value))

    @field_validator("vocabulary_highlights")
    @classmethod
    def cap_vocabulary_highlights(cls, v: list[VocabularyHighlight]) -> list[VocabularyHighlight]:
        return list(v)[:6]

    @field_validator("strong_spans")
    @classmethod
    def cap_strong_spans(cls, v: list[StrongSpan]) -> list[StrongSpan]:
        return list(v)[:4]


class DiagnosticEvaluateWritingRequest(BaseModel):
    client_attempt_id: str = Field(min_length=1, max_length=128)
    task_part: int = Field(default=1, ge=1, le=2)
    question: str = Field(min_length=1, max_length=8000)
    essay: str = Field(min_length=1, max_length=50000)
    visual_description: str = Field(default="", max_length=8000)
    target_band: float | None = Field(default=None, ge=0, le=9)


class WritingCriterionScores(BaseModel):
    task_achievement: float
    coherence: float
    lexical_resource: float
    grammar: float


class WritingFeedback(BaseModel):
    strengths: list[str]
    weaknesses: list[str]
    improvement_tips: list[str]
    next_band_advice: str = ""
    vocabulary_highlights: list[VocabularyHighlight] = Field(default_factory=list)
    strong_spans: list[StrongSpan] = Field(default_factory=list)


class WritingEvaluationMetadata(BaseModel):
    word_count: int
    sentence_count: int
    paragraph_count: int


class DiagnosticEvaluateWritingResponse(BaseModel):
    status: Literal["success", "complete"] = "success"
    evaluation_id: str
    writing_band: float
    scores: WritingCriterionScores
    feedback: WritingFeedback
    metadata: WritingEvaluationMetadata
    warnings: list[str] = Field(default_factory=list)
    spelling_mistakes: list[SpellingMistake] = Field(default_factory=list)
    grammar_mistakes: list[GrammarMistake] = Field(default_factory=list)
    provider: str | None = None
    next_band_advice: str = ""
    confidence: float = 0.5
    vocabulary_highlights: list[VocabularyHighlight] = Field(default_factory=list)
    strong_spans: list[StrongSpan] = Field(default_factory=list)
    essay_hash: str | None = None


class DiagnosticEvaluateWritingPendingResponse(BaseModel):
    status: Literal["pending"] = "pending"
    essay_hash: str
    client_attempt_id: str


class DiagnosticEvaluateWritingFailedResponse(BaseModel):
    status: Literal["failed"] = "failed"
    essay_hash: str | None = None
    client_attempt_id: str
    error: str = "AI evaluation failed."


DiagnosticWritingEvalStartResponse = (
    DiagnosticEvaluateWritingResponse | DiagnosticEvaluateWritingPendingResponse
)

DiagnosticWritingEvalStatusResponse = (
    DiagnosticEvaluateWritingResponse
    | DiagnosticEvaluateWritingPendingResponse
    | DiagnosticEvaluateWritingFailedResponse
)


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


def feedback_from_evaluation(ev: EvaluationResponse) -> dict[str, Any]:
    return {
        "strengths": ev.strengths,
        "weaknesses": ev.weaknesses,
        "improvement_tips": ev.improvement_tips,
        "spelling_mistakes": [m.model_dump() for m in ev.spelling_mistakes],
        "grammar_mistakes": [m.model_dump() for m in ev.grammar_mistakes],
        "spelling_error_count": ev.spelling_error_count,
        "next_band_advice": ev.next_band_advice,
        "confidence": ev.confidence,
        "vocabulary_highlights": [m.model_dump() for m in ev.vocabulary_highlights],
        "strong_spans": [m.model_dump() for m in ev.strong_spans],
    }


def _provider_from_row(row: dict[str, Any]) -> str | None:
    raw = row.get("raw_ai_response")
    if isinstance(raw, dict):
        used = raw.get("provider_used")
        if isinstance(used, str) and used:
            if used == "anthropic_claude":
                return "claude"
            if used == "groq":
                return "groq"
            return used
    return None


def _mistakes_from_feedback(feedback: dict[str, Any], key: str, model: type[SpellingMistake] | type[GrammarMistake]) -> list:
    raw = feedback.get(key) or []
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if isinstance(item, dict):
            try:
                out.append(model.model_validate(item))
            except Exception:
                continue
    return out


def _vocab_from_feedback(feedback: dict[str, Any]) -> list[VocabularyHighlight]:
    raw = feedback.get("vocabulary_highlights") or []
    if not isinstance(raw, list):
        return []
    out: list[VocabularyHighlight] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                out.append(VocabularyHighlight.model_validate(item))
            except Exception:
                continue
    return out[:6]


def _spans_from_feedback(feedback: dict[str, Any]) -> list[StrongSpan]:
    raw = feedback.get("strong_spans") or []
    if not isinstance(raw, list):
        return []
    out: list[StrongSpan] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                out.append(StrongSpan.model_validate(item))
            except Exception:
                continue
    return out[:4]


def _confidence_from_feedback(feedback: dict[str, Any]) -> float:
    raw = feedback.get("confidence", 0.5)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.5
    if not math.isfinite(value):
        return 0.5
    return max(0.0, min(1.0, value))


def row_to_public_response(row: dict[str, Any]) -> DiagnosticEvaluateWritingResponse:
    criteria = row.get("criteria_scores") or {}
    feedback = row.get("feedback") or {}
    words = int(row.get("word_count") or 0)
    task_part = int(row.get("task_part") or 1)
    next_band = str(feedback.get("next_band_advice") or "").strip()
    confidence = _confidence_from_feedback(feedback)
    vocab = _vocab_from_feedback(feedback)
    spans = _spans_from_feedback(feedback)
    essay_hash = row.get("essay_hash")
    return DiagnosticEvaluateWritingResponse(
        status="complete",
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
            next_band_advice=next_band,
            vocabulary_highlights=vocab,
            strong_spans=spans,
        ),
        metadata=WritingEvaluationMetadata(
            word_count=words,
            sentence_count=int(row.get("sentence_count") or 0),
            paragraph_count=int(row.get("paragraph_count") or 0),
        ),
        warnings=length_warnings(task_part=task_part, word_count=words),
        spelling_mistakes=_mistakes_from_feedback(feedback, "spelling_mistakes", SpellingMistake),
        grammar_mistakes=_mistakes_from_feedback(feedback, "grammar_mistakes", GrammarMistake),
        provider=_provider_from_row(row),
        next_band_advice=next_band,
        confidence=confidence,
        vocabulary_highlights=vocab,
        strong_spans=spans,
        essay_hash=str(essay_hash) if essay_hash else None,
    )


def evaluation_to_ai_scores(
    evaluation: EvaluationResponse,
    *,
    model_name: str,
    provider_used: str,
) -> dict[str, Any]:
    """Map EvaluationResponse to writing_reviews.ai_scores payload."""
    return {
        "ai_band": evaluation.overall_band,
        "criteria": criteria_from_evaluation(evaluation),
        "strengths": list(evaluation.strengths),
        "improvements": [*evaluation.weaknesses, *evaluation.improvement_tips],
        "spelling_mistakes": [m.model_dump() for m in evaluation.spelling_mistakes],
        "grammar_mistakes": [m.model_dump() for m in evaluation.grammar_mistakes],
        "spelling_error_count": evaluation.spelling_error_count,
        "next_band_advice": evaluation.next_band_advice,
        "confidence": evaluation.confidence,
        "vocabulary_highlights": [m.model_dump() for m in evaluation.vocabulary_highlights],
        "strong_spans": [m.model_dump() for m in evaluation.strong_spans],
        "model_name": model_name,
        "provider_used": provider_used,
    }


def build_stub_evaluation(*, task_part: int = 2, essay: str = "") -> EvaluationResponse:
    """Schema-valid stub for WRITING_EVAL_STUB mode (UI annotation paths exercise)."""
    snippet = (essay or "The response addresses the task.").strip()
    context = snippet[:60] if len(snippet) >= 20 else snippet
    ta_label = "task response" if task_part == 2 else "overview and key features"
    strong_quote = snippet[:80] if len(snippet) >= 20 else "The response addresses the task."
    return EvaluationResponse(
        overall_band=6.0,
        task_achievement=6.0,
        coherence=6.0,
        lexical_resource=6.0,
        grammar=5.5,
        strengths=[
            f"Addresses the {ta_label} with a clear main idea.",
            "Ideas are generally organised into paragraphs.",
        ],
        weaknesses=[
            "Some sentences are simple and could be linked more precisely.",
            "A few vocabulary and accuracy issues limit the band.",
        ],
        improvement_tips=[
            "Extend one body paragraph with a concrete example.",
            "Check spelling of topic words before submitting.",
            "Use a wider range of cohesive devices.",
        ],
        spelling_mistakes=[
            SpellingMistake(
                original="goverment",
                correction="government",
                context=context or "the goverment should",
            )
        ],
        grammar_mistakes=[
            GrammarMistake(
                original="people is",
                correction="people are",
                issue="Subject-verb agreement",
            )
        ],
        spelling_error_count=1,
        next_band_advice="Add one sentence that clearly summarises the main trend before listing details.",
        confidence=0.72,
        vocabulary_highlights=[
            VocabularyHighlight(
                word="good",
                polarity="weak",
                alternatives=["beneficial", "valuable"],
            ),
            VocabularyHighlight(
                word="crucial",
                polarity="strong",
                alternatives=[],
            ),
        ],
        strong_spans=[
            StrongSpan(
                text=strong_quote,
                reason="Clear opening that addresses the task",
            )
        ],
    )
