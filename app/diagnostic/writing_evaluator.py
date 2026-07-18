"""Diagnostic writing evaluation — stub / Claude / Groq, shared cache, retry.

Supports synchronous evaluation (tests / legacy) and background enqueue + status
polling for the diagnostic funnel UX.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Literal

from fastapi import BackgroundTasks, HTTPException, Request, status

from app.config import get_settings
from app.diagnostic.evaluation_schemas import (
    DiagnosticEvaluateWritingFailedResponse,
    DiagnosticEvaluateWritingPendingResponse,
    DiagnosticEvaluateWritingRequest,
    DiagnosticEvaluateWritingResponse,
    DiagnosticWritingEvalStartResponse,
    DiagnosticWritingEvalStatusResponse,
    row_to_public_response,
)
from app.diagnostic.rate_limit import record_evaluate_writing_rate_limit
from app.writing.eval_cache import (
    EVALUATION_SOURCE_AI,
    EVALUATION_SOURCE_STUB,
    EVALUATION_TYPE,
    is_cache_valid,
    lookup_by_client_attempt,
    lookup_by_essay_hash,
    persist_evaluation,
)
from app.writing.eval_utils import (
    MIN_WORDS_FOR_AI,
    compute_essay_hash,
    count_paragraphs,
    count_sentences,
    sanitize_essay,
    word_count,
    writing_cache_model_key,
)
from app.diagnostic.writing_prompt import resolve_prompt_version
from app.writing.providers.factory import evaluate_writing_essay, writing_eval_configured

logger = logging.getLogger(__name__)

# Backward-compatible aliases for tests and callers.
_is_cache_valid = is_cache_valid
_lookup_by_essay_hash = lookup_by_essay_hash
_lookup_by_client_attempt = lookup_by_client_attempt
_persist_evaluation = persist_evaluation

PendingStatus = Literal["pending", "failed"]

# In-process registry for jobs that have not yet persisted a cache row.
# Keyed by client_attempt_id. Completed results live in diagnostic_ai_evaluations.
_eval_jobs: dict[str, dict[str, Any]] = {}


def _resolve_cached_row(
    *,
    essay_hash: str,
    client_attempt_id: str,
):
    # Use module aliases so tests can patch _lookup_by_essay_hash / _lookup_by_client_attempt
    for row in (_lookup_by_essay_hash(essay_hash), _lookup_by_client_attempt(client_attempt_id)):
        if _is_cache_valid(row):
            return row
    return None


def _mark_job(
    client_attempt_id: str,
    *,
    job_status: PendingStatus,
    essay_hash: str,
    error: str | None = None,
) -> None:
    _eval_jobs[client_attempt_id] = {
        "status": job_status,
        "essay_hash": essay_hash,
        "error": error,
        "ts": time.time(),
    }


def _clear_job(client_attempt_id: str) -> None:
    _eval_jobs.pop(client_attempt_id, None)


def _prepare_evaluation_inputs(
    body: DiagnosticEvaluateWritingRequest,
) -> tuple[str, str, str, float | None, str, int, str]:
    """Sanitize + validate inputs. Returns cleaned fields and essay_hash."""
    original_essay = body.essay.strip()
    question = body.question.strip()
    visual_description = (body.visual_description or "").strip()
    target_band = body.target_band
    cleaned_essay = sanitize_essay(original_essay, question)
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
        prompt_version=resolve_prompt_version(),
        model_name=writing_cache_model_key(),
        visual_description=visual_description,
    )
    return (
        original_essay,
        question,
        visual_description,
        target_band,
        cleaned_essay,
        words,
        essay_hash,
    )


async def _persist_ai_result(
    *,
    client_attempt_id: str,
    essay_hash: str,
    task_part: int,
    question: str,
    original_essay: str,
    cleaned_essay: str,
    words: int,
    visual_description: str,
    target_band: float | None,
) -> dict[str, Any]:
    sentences = count_sentences(cleaned_essay)
    paragraphs = count_paragraphs(cleaned_essay)
    result = await evaluate_writing_essay(
        task_part=task_part,
        question=question,
        essay=cleaned_essay,
        visual_description=visual_description or None,
        target_band=target_band,
    )
    evaluation_source = (
        EVALUATION_SOURCE_STUB
        if get_settings().writing_eval_stub
        else EVALUATION_SOURCE_AI
    )
    row = _persist_evaluation(
        client_attempt_id=client_attempt_id,
        essay_hash=essay_hash,
        task_part=task_part,
        question=question,
        original_essay=original_essay,
        cleaned_essay=cleaned_essay,
        evaluation=result.evaluation,
        words=words,
        sentences=sentences,
        paragraphs=paragraphs,
        raw_ai_response=result.raw_store,
        prompt_version=result.prompt_version,
        model_name=result.model_name,
        evaluation_source=evaluation_source,
    )
    logger.info(
        "Evaluation persisted (id=%s, source=%s, band=%s, model=%s, provider=%s)",
        row.get("id"),
        evaluation_source,
        result.evaluation.overall_band,
        result.model_name or "-",
        result.provider_used,
    )
    return row


async def _run_diagnostic_writing_eval_async(
    *,
    client_attempt_id: str,
    essay_hash: str,
    task_part: int,
    question: str,
    original_essay: str,
    cleaned_essay: str,
    words: int,
    visual_description: str,
    target_band: float | None,
) -> None:
    try:
        # Another request may have already cached this essay.
        cached = _resolve_cached_row(
            essay_hash=essay_hash,
            client_attempt_id=client_attempt_id,
        )
        if cached:
            _clear_job(client_attempt_id)
            return
        await _persist_ai_result(
            client_attempt_id=client_attempt_id,
            essay_hash=essay_hash,
            task_part=task_part,
            question=question,
            original_essay=original_essay,
            cleaned_essay=cleaned_essay,
            words=words,
            visual_description=visual_description,
            target_band=target_band,
        )
        _clear_job(client_attempt_id)
    except Exception as exc:
        logger.exception(
            "Background writing evaluation failed (attempt=%s)",
            client_attempt_id,
        )
        _mark_job(
            client_attempt_id,
            job_status="failed",
            essay_hash=essay_hash,
            error=str(exc) or "AI evaluation failed.",
        )


def _run_diagnostic_writing_eval(
    *,
    client_attempt_id: str,
    essay_hash: str,
    task_part: int,
    question: str,
    original_essay: str,
    cleaned_essay: str,
    words: int,
    visual_description: str,
    target_band: float | None,
) -> None:
    """Sync entry for FastAPI BackgroundTasks; never raises to callers."""
    try:
        asyncio.run(
            _run_diagnostic_writing_eval_async(
                client_attempt_id=client_attempt_id,
                essay_hash=essay_hash,
                task_part=task_part,
                question=question,
                original_essay=original_essay,
                cleaned_essay=cleaned_essay,
                words=words,
                visual_description=visual_description,
                target_band=target_band,
            )
        )
    except Exception:
        logger.exception(
            "_run_diagnostic_writing_eval failed for attempt %s",
            client_attempt_id,
        )
        _mark_job(
            client_attempt_id,
            job_status="failed",
            essay_hash=essay_hash,
            error="AI evaluation failed.",
        )


async def start_diagnostic_writing_evaluation(
    body: DiagnosticEvaluateWritingRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> DiagnosticWritingEvalStartResponse:
    """Enqueue evaluation (or return cache hit). Never blocks on the LLM call."""
    (
        original_essay,
        question,
        visual_description,
        target_band,
        cleaned_essay,
        words,
        essay_hash,
    ) = _prepare_evaluation_inputs(body)

    logger.info(
        "Writing evaluation requested (attempt=%s, task_part=%s, cleaned_words=%s)",
        body.client_attempt_id,
        body.task_part,
        words,
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
        _clear_job(body.client_attempt_id)
        return row_to_public_response(cached)

    # Already running for this attempt — return pending without re-enqueueing.
    existing = _eval_jobs.get(body.client_attempt_id)
    if existing and existing.get("status") == "pending":
        return DiagnosticEvaluateWritingPendingResponse(
            essay_hash=str(existing.get("essay_hash") or essay_hash),
            client_attempt_id=body.client_attempt_id,
        )

    record_evaluate_writing_rate_limit(request)

    if not writing_eval_configured():
        logger.error("No writing LLM provider configured")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI writing evaluation is not configured. Please try again later.",
        )

    _mark_job(
        body.client_attempt_id,
        job_status="pending",
        essay_hash=essay_hash,
    )
    background_tasks.add_task(
        _run_diagnostic_writing_eval,
        client_attempt_id=body.client_attempt_id,
        essay_hash=essay_hash,
        task_part=body.task_part,
        question=question,
        original_essay=original_essay,
        cleaned_essay=cleaned_essay,
        words=words,
        visual_description=visual_description,
        target_band=target_band,
    )
    logger.info(
        "Writing evaluation enqueued (attempt=%s, essay_hash=%s)",
        body.client_attempt_id,
        essay_hash[:12],
    )
    return DiagnosticEvaluateWritingPendingResponse(
        essay_hash=essay_hash,
        client_attempt_id=body.client_attempt_id,
    )


def get_diagnostic_writing_status(
    *,
    client_attempt_id: str,
    essay_hash: str | None = None,
) -> DiagnosticWritingEvalStatusResponse:
    """Poll evaluation status for a diagnostic attempt."""
    cached = None
    if essay_hash:
        row = _lookup_by_essay_hash(essay_hash)
        if _is_cache_valid(row):
            cached = row
    if cached is None:
        row = _lookup_by_client_attempt(client_attempt_id)
        if _is_cache_valid(row):
            cached = row
    if cached:
        _clear_job(client_attempt_id)
        return row_to_public_response(cached)

    job = _eval_jobs.get(client_attempt_id)
    if job and job.get("status") == "failed":
        return DiagnosticEvaluateWritingFailedResponse(
            client_attempt_id=client_attempt_id,
            essay_hash=job.get("essay_hash") or essay_hash,
            error=str(job.get("error") or "AI evaluation failed."),
        )

    return DiagnosticEvaluateWritingPendingResponse(
        essay_hash=str((job or {}).get("essay_hash") or essay_hash or ""),
        client_attempt_id=client_attempt_id,
    )


async def evaluate_diagnostic_writing(
    body: DiagnosticEvaluateWritingRequest,
    request: Request,
) -> DiagnosticEvaluateWritingResponse:
    """Synchronous evaluation (tests / legacy callers). Blocks until LLM returns."""
    (
        original_essay,
        question,
        visual_description,
        target_band,
        cleaned_essay,
        words,
        essay_hash,
    ) = _prepare_evaluation_inputs(body)

    logger.info(
        "Writing evaluation requested (attempt=%s, task_part=%s, cleaned_words=%s)",
        body.client_attempt_id,
        body.task_part,
        words,
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

    if not writing_eval_configured():
        logger.error("No writing LLM provider configured")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI writing evaluation is not configured. Please try again later.",
        )

    try:
        row = await _persist_ai_result(
            client_attempt_id=body.client_attempt_id,
            essay_hash=essay_hash,
            task_part=body.task_part,
            question=question,
            original_essay=original_essay,
            cleaned_essay=cleaned_essay,
            words=words,
            visual_description=visual_description,
            target_band=target_band,
        )
    except Exception as exc:
        logger.exception("Writing evaluation failed for diagnostic")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI evaluation is temporarily unavailable. Please try again.",
        ) from exc

    return row_to_public_response(row)


# Re-export for backward-compatible imports in tests and callers.
__all__ = [
    "EVALUATION_TYPE",
    "MIN_WORDS_FOR_AI",
    "compute_essay_hash",
    "count_paragraphs",
    "count_sentences",
    "evaluate_diagnostic_writing",
    "get_diagnostic_writing_status",
    "sanitize_essay",
    "start_diagnostic_writing_evaluation",
]
