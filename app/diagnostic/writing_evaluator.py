"""Diagnostic writing evaluation — Groq, cache, and retry."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from fastapi import HTTPException, Request, status
from pydantic import ValidationError

from app.config import get_settings
from app.db.supabase_client import get_supabase
from app.diagnostic.evaluation_schemas import (
    DiagnosticEvaluateWritingRequest,
    DiagnosticEvaluateWritingResponse,
    EvaluationResponse,
    criteria_from_evaluation,
    feedback_from_evaluation,
    reconcile_overall_band,
    row_to_public_response,
)
from app.diagnostic.groq_client import chat_completion_json, groq_configured
from app.diagnostic.rate_limit import record_evaluate_writing_rate_limit
from app.diagnostic.writing_prompt import (
    PROMPT_VERSION,
    RETRY_SUFFIX,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from app.writing.evaluation import min_words_for_part, word_count

logger = logging.getLogger(__name__)

EVALUATION_TYPE = "writing"
MIN_WORDS_FOR_AI = 30


def normalize_text(text: str) -> str:
    return " ".join(text.strip().split())


def sanitize_essay(essay: str, question: str) -> str:
    """Strip pasted task instructions so word count and scoring target the response."""
    text = essay.strip()
    if not text:
        return text

    question_text = question.strip()
    if question_text and question_text in text:
        text = text.replace(question_text, "", 1).strip()

    boilerplate_patterns = [
        r"You should spend about \d+ minutes on this task\.?\s*",
        r"Summarise the information by selecting and reporting the main features.*?\.\s*",
        r"Write at least \d+ words\.?\s*",
        r"The (?:bar chart|chart|graph|table|diagram) below shows.*?\.\s*",
    ]
    for pattern in boilerplate_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL)

    return text.strip() or essay.strip()


def _coerce_parsed_evaluation(parsed: dict[str, Any], *, words: int, task_part: int) -> dict[str, Any]:
    """Ensure Groq JSON has non-empty feedback lists before Pydantic validation."""
    min_words = min_words_for_part(task_part)
    data = dict(parsed)

    if not data.get("strengths"):
        data["strengths"] = (
            ["You attempted to respond to the task."]
            if words > 0
            else ["No substantive response was provided."]
        )
    if not data.get("weaknesses"):
        if words < min_words:
            data["weaknesses"] = [
                f"The response is only {words} words — Task {task_part} requires at least {min_words}.",
            ]
        else:
            data["weaknesses"] = ["The response needs clearer task coverage and development."]
    if not data.get("improvement_tips"):
        data["improvement_tips"] = [
            f"Write a complete answer of at least {min_words} words with an overview, key features, and comparisons.",
        ]

    return data


def compute_essay_hash(*, task_part: int, question: str, essay: str) -> str:
    payload = f"{task_part}\n{normalize_text(question)}\n{normalize_text(essay)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def count_sentences(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    parts = re.split(r"[.!?]+", stripped)
    return max(1, sum(1 for part in parts if part.strip()))


def count_paragraphs(text: str) -> int:
    if not text.strip():
        return 0
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    return max(1, len(paras))


def _parse_json_content(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("Expected JSON object")
    return parsed


def _is_cache_valid(row: dict[str, Any] | None) -> bool:
    """Only AI evaluations are cached; legacy fallback rows are never served."""
    if not row:
        return False
    return row.get("evaluation_source") == "ai"


def _lookup_by_essay_hash(essay_hash: str) -> dict[str, Any] | None:
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


def _lookup_by_client_attempt(client_attempt_id: str) -> dict[str, Any] | None:
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


def _resolve_cached_row(
    *,
    essay_hash: str,
    client_attempt_id: str,
) -> dict[str, Any] | None:
    for row in (_lookup_by_essay_hash(essay_hash), _lookup_by_client_attempt(client_attempt_id)):
        if _is_cache_valid(row):
            return row
    return None


async def _call_groq_evaluation(
    *,
    task_part: int,
    question: str,
    essay: str,
) -> tuple[EvaluationResponse, dict[str, Any], str, str]:
    settings = get_settings()
    model_name = settings.groq_model
    user_prompt = build_user_prompt(task_part=task_part, question=question, essay=essay)
    raw_store: dict[str, Any] | str | None = None
    last_error: Exception | None = None

    logger.info("Calling Groq model: %s", model_name)

    for attempt in range(2):
        prompt = user_prompt if attempt == 0 else user_prompt + RETRY_SUFFIX
        try:
            content, raw_response = await chat_completion_json(
                system=SYSTEM_PROMPT,
                user=prompt,
                model=model_name,
            )
            logger.info("Groq response received (attempt %s)", attempt + 1)
            raw_store = {"content": content, "response": raw_response}
            parsed = _coerce_parsed_evaluation(
                _parse_json_content(content),
                words=word_count(essay),
                task_part=task_part,
            )
            evaluation = EvaluationResponse.model_validate(parsed)
            ai_overall = evaluation.overall_band
            evaluation, reconciled = reconcile_overall_band(evaluation)
            if reconciled and isinstance(raw_store, dict):
                raw_store["overall_band_reconciled"] = True
                raw_store["ai_overall_band"] = ai_overall
                raw_store["calculated_overall_band"] = evaluation.overall_band
                logger.info(
                    "Overall band reconciled: ai=%s calculated=%s",
                    ai_overall,
                    evaluation.overall_band,
                )
            return evaluation, raw_store, PROMPT_VERSION, model_name
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            logger.warning("Groq evaluation validation failed (attempt %s): %s", attempt + 1, exc)
        except Exception as exc:
            last_error = exc
            logger.warning("Groq evaluation call failed (attempt %s): %s", attempt + 1, exc)
            break

    raise RuntimeError(str(last_error) if last_error else "Groq evaluation failed")


def _persist_evaluation(
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

    existing = _lookup_by_essay_hash(essay_hash) or _lookup_by_client_attempt(client_attempt_id)
    if existing:
        return existing
    raise RuntimeError("Could not persist diagnostic writing evaluation.")


async def evaluate_diagnostic_writing(
    body: DiagnosticEvaluateWritingRequest,
    request: Request,
) -> DiagnosticEvaluateWritingResponse:
    original_essay = body.essay.strip()
    question = body.question.strip()
    cleaned_essay = sanitize_essay(original_essay, question)
    logger.info(
        "Writing evaluation requested (attempt=%s, task_part=%s, cleaned_words=%s)",
        body.client_attempt_id,
        body.task_part,
        word_count(cleaned_essay),
    )

    words = word_count(cleaned_essay)
    if words < MIN_WORDS_FOR_AI:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Response too short for IELTS evaluation.",
        )

    essay_hash = compute_essay_hash(
        task_part=body.task_part,
        question=question,
        essay=cleaned_essay,
    )

    cached = _resolve_cached_row(
        essay_hash=essay_hash,
        client_attempt_id=body.client_attempt_id,
    )
    if cached:
        logger.info(
            "Evaluation cache hit (source=%s, id=%s)",
            cached.get("evaluation_source"),
            cached.get("id"),
        )
        return row_to_public_response(cached)

    record_evaluate_writing_rate_limit(request)

    if not groq_configured():
        logger.error("GROQ_API_KEY missing — cannot evaluate diagnostic writing")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI writing evaluation is not configured. Please try again later.",
        )

    sentences = count_sentences(cleaned_essay)
    paragraphs = count_paragraphs(cleaned_essay)

    try:
        evaluation, raw_ai_response, prompt_version, model_name = await _call_groq_evaluation(
            task_part=body.task_part,
            question=question,
            essay=cleaned_essay,
        )
    except Exception as exc:
        logger.exception("Groq evaluation failed for diagnostic writing")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI evaluation is temporarily unavailable. Please try again.",
        ) from exc

    evaluation_source = "ai"

    row = _persist_evaluation(
        client_attempt_id=body.client_attempt_id,
        essay_hash=essay_hash,
        task_part=body.task_part,
        question=question,
        original_essay=original_essay,
        cleaned_essay=cleaned_essay,
        evaluation=evaluation,
        words=words,
        sentences=sentences,
        paragraphs=paragraphs,
        raw_ai_response=raw_ai_response,
        prompt_version=prompt_version,
        model_name=model_name,
        evaluation_source=evaluation_source,
    )
    logger.info(
        "Evaluation persisted (id=%s, source=%s, band=%s, model=%s)",
        row.get("id"),
        evaluation_source,
        evaluation.overall_band,
        model_name or "-",
    )
    return row_to_public_response(row)
