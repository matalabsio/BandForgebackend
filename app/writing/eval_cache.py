"""Shared essay_hash cache for diagnostic + mock writing AI evaluations."""

from __future__ import annotations

import logging
from typing import Any

from app.db.supabase_client import get_supabase
from app.diagnostic.evaluation_schemas import (
    EvaluationResponse,
    GrammarMistake,
    SpellingMistake,
    StrongSpan,
    VocabularyHighlight,
    criteria_from_evaluation,
    feedback_from_evaluation,
)
from app.writing.eval_utils import compute_essay_hash

logger = logging.getLogger(__name__)

EVALUATION_TYPE = "writing"
EVALUATION_SOURCE_AI = "ai"
EVALUATION_SOURCE_STUB = "ai_stub"
EVALUATION_SOURCE_FALLBACK = "fallback"

CACHEABLE_SOURCES = frozenset({EVALUATION_SOURCE_AI, EVALUATION_SOURCE_STUB})


def cache_attempt_id_for_hash(essay_hash: str) -> str:
    """Synthetic client_attempt_id for non-diagnostic callers (UNIQUE-safe)."""
    return f"cache:{essay_hash}"


def is_cache_valid(row: dict[str, Any] | None) -> bool:
    """AI and stub rows are cacheable; legacy fallback rows are never served."""
    if not row:
        return False
    return row.get("evaluation_source") in CACHEABLE_SOURCES


def lookup_by_essay_hash(essay_hash: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table("diagnostic_ai_evaluations")
        .select("*")
        .eq("essay_hash", essay_hash)
        .eq("evaluation_type", EVALUATION_TYPE)
        .maybe_single()
        .execute()
    )
    row = getattr(result, "data", None)
    return row if isinstance(row, dict) else None


def lookup_by_client_attempt(client_attempt_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table("diagnostic_ai_evaluations")
        .select("*")
        .eq("client_attempt_id", client_attempt_id)
        .eq("evaluation_type", EVALUATION_TYPE)
        .maybe_single()
        .execute()
    )
    row = getattr(result, "data", None)
    return row if isinstance(row, dict) else None


def lookup_cached_evaluation(
    essay_hash: str,
    *,
    client_attempt_id: str | None = None,
) -> dict[str, Any] | None:
    rows: list[dict[str, Any] | None] = [lookup_by_essay_hash(essay_hash)]
    if client_attempt_id:
        rows.append(lookup_by_client_attempt(client_attempt_id))
    for row in rows:
        if is_cache_valid(row):
            return row
    return None


def persist_evaluation(
    *,
    client_attempt_id: str,
    essay_hash: str,
    task_part: int,
    question: str,
    original_essay: str,
    cleaned_essay: str,
    evaluation: EvaluationResponse,
    words: int,
    sentences: int,
    paragraphs: int,
    raw_ai_response: dict[str, Any] | str | None,
    prompt_version: str,
    model_name: str | None,
    evaluation_source: str,
) -> dict[str, Any]:
    sb = get_supabase()
    row = {
        "evaluation_type": EVALUATION_TYPE,
        "client_attempt_id": client_attempt_id,
        "essay_hash": essay_hash,
        "task_part": task_part,
        "question_text": question,
        "essay_text": cleaned_essay,
        "original_essay_text": original_essay,
        "cleaned_essay_text": cleaned_essay,
        "word_count": words,
        "sentence_count": sentences,
        "paragraph_count": paragraphs,
        "overall_band": evaluation.overall_band,
        "criteria_scores": criteria_from_evaluation(evaluation),
        "feedback": feedback_from_evaluation(evaluation),
        "raw_ai_response": raw_ai_response,
        "prompt_version": prompt_version,
        "model_name": model_name,
        "evaluation_source": evaluation_source,
    }
    inserted = sb.table("diagnostic_ai_evaluations").insert(row).execute()
    rows = inserted.data or []
    if rows:
        return rows[0]

    existing = lookup_by_essay_hash(essay_hash) or lookup_by_client_attempt(
        client_attempt_id
    )
    if existing:
        return existing
    raise RuntimeError("Could not persist writing evaluation.")


def _mistakes_from_feedback(
    feedback: dict[str, Any],
    key: str,
    model: type[SpellingMistake] | type[GrammarMistake],
) -> list:
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


def row_to_evaluation_response(row: dict[str, Any]) -> EvaluationResponse | None:
    """Rebuild EvaluationResponse from a cached diagnostic_ai_evaluations row."""
    criteria = row.get("criteria_scores") or {}
    feedback = row.get("feedback") or {}
    try:
        vocab_raw = feedback.get("vocabulary_highlights") or []
        spans_raw = feedback.get("strong_spans") or []
        vocab: list[VocabularyHighlight] = []
        spans: list[StrongSpan] = []
        if isinstance(vocab_raw, list):
            for item in vocab_raw:
                if isinstance(item, dict):
                    try:
                        vocab.append(VocabularyHighlight.model_validate(item))
                    except Exception:
                        continue
        if isinstance(spans_raw, list):
            for item in spans_raw:
                if isinstance(item, dict):
                    try:
                        spans.append(StrongSpan.model_validate(item))
                    except Exception:
                        continue
        confidence_raw = feedback.get("confidence", 0.5)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.5
        return EvaluationResponse(
            overall_band=float(row["overall_band"]),
            task_achievement=float(criteria.get("task_achievement", 0)),
            coherence=float(criteria.get("coherence", 0)),
            lexical_resource=float(criteria.get("lexical_resource", 0)),
            grammar=float(criteria.get("grammar", 0)),
            strengths=list(feedback.get("strengths") or ["Cached evaluation."]),
            weaknesses=list(feedback.get("weaknesses") or ["See stored feedback."]),
            improvement_tips=list(
                feedback.get("improvement_tips") or ["Re-evaluate for fresh tips."]
            ),
            spelling_mistakes=_mistakes_from_feedback(
                feedback, "spelling_mistakes", SpellingMistake
            ),
            grammar_mistakes=_mistakes_from_feedback(
                feedback, "grammar_mistakes", GrammarMistake
            ),
            spelling_error_count=int(feedback.get("spelling_error_count") or 0),
            next_band_advice=str(feedback.get("next_band_advice") or ""),
            confidence=confidence,
            vocabulary_highlights=vocab[:6],
            strong_spans=spans[:4],
        )
    except Exception:
        logger.exception("Failed to rebuild EvaluationResponse from cache row")
        return None


__all__ = [
    "CACHEABLE_SOURCES",
    "EVALUATION_SOURCE_AI",
    "EVALUATION_SOURCE_FALLBACK",
    "EVALUATION_SOURCE_STUB",
    "EVALUATION_TYPE",
    "cache_attempt_id_for_hash",
    "compute_essay_hash",
    "is_cache_valid",
    "lookup_by_client_attempt",
    "lookup_by_essay_hash",
    "lookup_cached_evaluation",
    "persist_evaluation",
    "row_to_evaluation_response",
]
