"""Groq-only writing evaluation for intern screening."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import BackgroundTasks, HTTPException, status

from app.diagnostic.evaluation_schemas import (
    DiagnosticEvaluateWritingFailedResponse,
    DiagnosticEvaluateWritingPendingResponse,
    DiagnosticEvaluateWritingRequest,
    DiagnosticEvaluateWritingResponse,
    WritingCriterionScores,
    WritingEvaluationMetadata,
    WritingFeedback,
    length_warnings,
)
from app.diagnostic.groq_client import groq_configured
from app.intern import repository
from app.writing.eval_utils import (
    MIN_WORDS_FOR_AI,
    compute_essay_hash,
    count_paragraphs,
    count_sentences,
    sanitize_essay,
    word_count,
)
from app.writing.providers.evaluation_call import call_writing_evaluation_with_retry
from app.writing.providers.groq_eval import GroqWritingProvider
from app.writing.providers.stub_eval import StubWritingProvider

logger = logging.getLogger(__name__)

_eval_jobs: dict[str, dict[str, Any]] = {}


def _mark_job(application_id: str, *, job_status: str, essay_hash: str, error: str | None = None) -> None:
    _eval_jobs[application_id] = {
        "status": job_status,
        "essay_hash": essay_hash,
        "error": error,
        "ts": time.time(),
    }


def _clear_job(application_id: str) -> None:
    _eval_jobs.pop(application_id, None)


def _public_from_payload(payload: dict[str, Any]) -> DiagnosticEvaluateWritingResponse:
    scores = payload.get("scores") or {}
    feedback = payload.get("feedback") or {}
    metadata = payload.get("metadata") or {}
    return DiagnosticEvaluateWritingResponse(
        status="complete",
        evaluation_id=str(payload.get("evaluation_id") or payload.get("essay_hash") or "intern-writing"),
        writing_band=float(payload.get("writing_band") or 0),
        scores=WritingCriterionScores(
            task_achievement=float(scores.get("task_achievement") or 0),
            coherence=float(scores.get("coherence") or 0),
            lexical_resource=float(scores.get("lexical_resource") or 0),
            grammar=float(scores.get("grammar") or 0),
        ),
        feedback=WritingFeedback(
            strengths=list(feedback.get("strengths") or ["Attempt recorded."]),
            weaknesses=list(feedback.get("weaknesses") or ["Keep developing ideas."]),
            improvement_tips=list(feedback.get("improvement_tips") or ["Write a fuller response."]),
            next_band_advice=str(feedback.get("next_band_advice") or payload.get("next_band_advice") or ""),
        ),
        metadata=WritingEvaluationMetadata(
            word_count=int(metadata.get("word_count") or 0),
            sentence_count=int(metadata.get("sentence_count") or 0),
            paragraph_count=int(metadata.get("paragraph_count") or 0),
        ),
        warnings=list(payload.get("warnings") or []),
        spelling_mistakes=payload.get("spelling_mistakes") or [],
        grammar_mistakes=payload.get("grammar_mistakes") or [],
        provider=payload.get("provider"),
        next_band_advice=str(payload.get("next_band_advice") or ""),
        confidence=float(payload.get("confidence") or 0.5),
        vocabulary_highlights=payload.get("vocabulary_highlights") or [],
        strong_spans=payload.get("strong_spans") or [],
        essay_hash=payload.get("essay_hash"),
    )


async def _run_groq_writing(
    *,
    task_part: int,
    question: str,
    essay: str,
    visual_description: str | None,
    target_band: float | None,
):
    if groq_configured():
        provider = GroqWritingProvider()
    else:
        provider = StubWritingProvider(task_part=task_part, essay=essay)

    async def llm_call(system: str, user: str) -> tuple[str, dict]:
        return await provider.chat_json(system=system, user=user)

    return await call_writing_evaluation_with_retry(
        llm_call=llm_call,
        task_part=task_part,
        question=question,
        essay=essay,
        provider_label=provider.name,
        model_name=provider.model,
        provider_used=provider.name,
        visual_description=visual_description,
        target_band=target_band,
    )


def _payload_from_result(result, *, essay_hash: str, cleaned_essay: str) -> dict[str, Any]:
    evaluation = result.evaluation
    words = word_count(cleaned_essay)
    return {
        "evaluation_id": essay_hash,
        "essay_hash": essay_hash,
        "writing_band": evaluation.overall_band,
        "scores": {
            "task_achievement": evaluation.task_achievement,
            "coherence": evaluation.coherence,
            "lexical_resource": evaluation.lexical_resource,
            "grammar": evaluation.grammar,
        },
        "feedback": {
            "strengths": evaluation.strengths,
            "weaknesses": evaluation.weaknesses,
            "improvement_tips": evaluation.improvement_tips,
            "next_band_advice": evaluation.next_band_advice,
        },
        "metadata": {
            "word_count": words,
            "sentence_count": count_sentences(cleaned_essay),
            "paragraph_count": count_paragraphs(cleaned_essay),
        },
        "warnings": length_warnings(task_part=1, word_count=words),
        "spelling_mistakes": [m.model_dump() for m in (evaluation.spelling_mistakes or [])],
        "grammar_mistakes": [m.model_dump() for m in (evaluation.grammar_mistakes or [])],
        "provider": result.provider_used,
        "next_band_advice": evaluation.next_band_advice,
        "confidence": evaluation.confidence,
        "vocabulary_highlights": [v.model_dump() for v in (evaluation.vocabulary_highlights or [])],
        "strong_spans": [s.model_dump() for s in (evaluation.strong_spans or [])],
    }


async def _run_job(
    *,
    application_id: str,
    essay_hash: str,
    task_part: int,
    question: str,
    cleaned_essay: str,
    visual_description: str | None,
    target_band: float | None,
) -> None:
    try:
        result = await _run_groq_writing(
            task_part=task_part,
            question=question,
            essay=cleaned_essay,
            visual_description=visual_description,
            target_band=target_band,
        )
        payload = _payload_from_result(result, essay_hash=essay_hash, cleaned_essay=cleaned_essay)
        repository.update_application(
            application_id,
            {
                "writing_evaluation": payload,
                "writing_band": payload["writing_band"],
                "writing_eval_pending": False,
                "writing_eval_essay_hash": essay_hash,
                "writing_eval_error": None,
            },
        )
        _clear_job(application_id)
    except Exception as exc:
        logger.exception("Intern writing eval failed (id=%s)", application_id)
        repository.update_application(
            application_id,
            {
                "writing_eval_pending": False,
                "writing_eval_error": str(exc) or "AI evaluation failed.",
            },
        )
        _mark_job(
            application_id,
            job_status="failed",
            essay_hash=essay_hash,
            error=str(exc) or "AI evaluation failed.",
        )


async def start_intern_writing_evaluation(
    *,
    application: dict[str, Any],
    body: DiagnosticEvaluateWritingRequest,
    background_tasks: BackgroundTasks,
) -> DiagnosticEvaluateWritingResponse | DiagnosticEvaluateWritingPendingResponse:
    application_id = str(application["id"])
    existing = application.get("writing_evaluation")
    if isinstance(existing, dict) and existing.get("writing_band") is not None:
        return _public_from_payload(existing)

    original = body.essay.strip()
    question = body.question.strip()
    visual = (body.visual_description or "").strip() or None
    cleaned = sanitize_essay(original, question)
    words = word_count(cleaned)
    if words < MIN_WORDS_FOR_AI:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Response too short for IELTS evaluation.",
        )
    essay_hash = compute_essay_hash(
        task_part=body.task_part,
        question=question,
        essay=cleaned,
        prompt_version="intern-groq-v1",
        model_name="groq",
        visual_description=visual or "",
    )

    repository.update_application(
        application_id,
        {
            "writing_eval_pending": True,
            "writing_eval_essay_hash": essay_hash,
            "writing_eval_error": None,
            "current_module": "speaking",
        },
    )
    _mark_job(application_id, job_status="pending", essay_hash=essay_hash)
    background_tasks.add_task(
        _run_job,
        application_id=application_id,
        essay_hash=essay_hash,
        task_part=body.task_part,
        question=question,
        cleaned_essay=cleaned,
        visual_description=visual,
        target_band=body.target_band,
    )
    return DiagnosticEvaluateWritingPendingResponse(
        essay_hash=essay_hash,
        client_attempt_id=application_id,
    )


def intern_writing_status(
    application: dict[str, Any],
) -> (
    DiagnosticEvaluateWritingResponse
    | DiagnosticEvaluateWritingPendingResponse
    | DiagnosticEvaluateWritingFailedResponse
):
    application_id = str(application["id"])
    payload = application.get("writing_evaluation")
    if isinstance(payload, dict) and payload.get("writing_band") is not None:
        return _public_from_payload(payload)

    error = application.get("writing_eval_error")
    if error:
        return DiagnosticEvaluateWritingFailedResponse(
            essay_hash=application.get("writing_eval_essay_hash"),
            client_attempt_id=application_id,
            error=str(error),
        )

    job = _eval_jobs.get(application_id)
    if job and job.get("status") == "failed":
        return DiagnosticEvaluateWritingFailedResponse(
            essay_hash=job.get("essay_hash"),
            client_attempt_id=application_id,
            error=str(job.get("error") or "AI evaluation failed."),
        )

    if application.get("writing_eval_pending") or (job and job.get("status") == "pending"):
        return DiagnosticEvaluateWritingPendingResponse(
            essay_hash=str(
                application.get("writing_eval_essay_hash")
                or (job or {}).get("essay_hash")
                or ""
            ),
            client_attempt_id=application_id,
        )

    return DiagnosticEvaluateWritingFailedResponse(
        essay_hash=application.get("writing_eval_essay_hash"),
        client_attempt_id=application_id,
        error="No writing evaluation found.",
    )
