"""Orchestrates Speaking Phase C: ASR -> metrics -> LLM eval -> persist."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx

from app.ai_ops.budget import check_claude_budget, check_groq_budget, consume_claude_eval, consume_groq_eval
from app.ai_ops.circuit import is_claude_circuit_open
from app.config import get_settings
from app.speaking import repository as repo
from app.speaking.evaluation_schemas import (
    SpeakingEvaluation,
    build_insufficient_speech_scores,
    build_stub_evaluation,
    evaluation_to_admin_criteria,
    validate_evidence_against_responses,
)
from app.speaking.fluency_metrics import aggregate_fluency_metrics, compute_fluency_metrics
from app.speaking.transcript_utils import (
    MIN_MEANINGFUL_WORDS_RESPONSE,
    attempt_meaningful_word_count,
    is_sufficient_attempt_speech,
    meaningful_word_count,
)
from app.speaking.providers.constants import (
    PROVIDER_NAME_ANTHROPIC_CLAUDE,
    PROVIDER_NAME_GROQ,
    PROVIDER_NAME_STUB,
    PROVIDER_VERSION,
)
from app.speaking.providers.factory import get_asr_provider, get_eval_provider_chain
from app.speaking.speaking_prompt import PROMPT_VERSION
from app.storage.r2 import get_object_bytes

logger = logging.getLogger(__name__)
EVALUATION_LEASE_SECONDS = 300
EVALUATION_MAX_ATTEMPTS = 4
EVALUATION_BACKOFF_SECONDS = (30, 120, 600, 1800)
_COMPLETED_EVALUATION_KEYS = {
    "ai_band",
    "evaluation",
    "fluency",
    "grammar",
    "lexical",
    "pronunciation",
}


def _filename_from_key(audio_key: str) -> str:
    name = audio_key.rsplit("/", 1)[-1]
    return name if "." in name else "recording.webm"


def _apply_pronunciation_advisory(evaluation: SpeakingEvaluation) -> None:
    """Make non-acoustic pronunciation output explicit and non-authoritative."""
    if evaluation.band_scores.P_confidence < 0.7:
        if "low_confidence_pronunciation" not in evaluation.reviewer_flags:
            evaluation.reviewer_flags.append("low_confidence_pronunciation")
    for evidence in evaluation.evidence_quotes:
        if evidence.criterion != "P" or not evidence.suggestion:
            continue
        if not evidence.suggestion.startswith("Transcript-inferred advisory only:"):
            evidence.suggestion = (
                f"Transcript-inferred advisory only: {evidence.suggestion}"
            )


def _normalize_ai_scores(
    *,
    status: str,
    transcript: str,
    words: list[dict[str, Any]],
    fluency_metrics: dict[str, Any],
    evaluation: SpeakingEvaluation,
    provider_asr: str,
    provider_eval: str,
    model_asr: str,
    model_eval: str,
    error: str | None = None,
) -> dict[str, Any]:
    _apply_pronunciation_advisory(evaluation)
    criteria = evaluation_to_admin_criteria(evaluation)
    return {
        "status": status,
        "ai_band": evaluation.band_scores.overall,
        **criteria,
        "provider_asr": provider_asr,
        "provider_eval": provider_eval,
        "model_asr": model_asr,
        "model_eval": model_eval,
        "provider_version": PROVIDER_VERSION,
        "prompt_version": PROMPT_VERSION,
        "words": words,
        "fluency_metrics": fluency_metrics,
        "evaluation": evaluation.model_dump(),
        "error": error,
    }


def _attempt_inputs(
    review: dict[str, Any],
    responses: list[dict[str, Any]],
    manifest: list[dict[str, Any]],
    *,
    provider_name: str,
    provider_model: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    prompts = {str(item["id"]): str(item.get("prompt") or "") for item in manifest}
    ordered = [
        {
            "response_id": str(row["id"]),
            "question_id": str(row["question_id"]),
            "part": int(row["part"]),
            "sequence_number": int(row["sequence_number"]),
            "prompt": prompts.get(str(row["question_id"]), ""),
            "transcript": str(row.get("transcript") or ""),
            "fluency_metrics": row.get("fluency_metrics") or {},
            "transcript_checksum": row.get("metrics_source_checksum")
            or row.get("content_sha256"),
        }
        for row in sorted(responses, key=lambda item: int(item["sequence_number"]))
    ]
    snapshot = aggregate_fluency_metrics(
        [{**row, "response_id": str(row["id"])} for row in responses]
    )
    identity = {
        "prompt_version": PROMPT_VERSION,
        "provider_version": PROVIDER_VERSION,
        "provider": provider_name,
        "model": provider_model,
        "manifest_hash": (review.get("submission_meta") or {}).get("manifest_hash"),
        "responses": ordered,
        "metrics_version": snapshot["version"],
        "metrics_source_checksum": snapshot["source_checksum"],
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    metrics = {
        "attempt_metrics": snapshot["attempt_metrics"],
        "part_metrics": snapshot["part_metrics"],
        "response_metrics": snapshot["response_metrics"],
        "metrics_version": snapshot["version"],
        "metrics_source_checksum": snapshot["source_checksum"],
    }
    return ordered, metrics, fingerprint


def _stub_attempt_evaluation(responses: list[dict[str, Any]]) -> SpeakingEvaluation:
    first = responses[0]
    evaluation = build_stub_evaluation(
        transcript=str(first["transcript"]), part=int(first["part"])
    )
    for evidence in evaluation.evidence_quotes:
        evidence.response_id = str(first["response_id"])
        evidence.question_id = str(first["question_id"])
        evidence.issue = "Observed transcript evidence"
        evidence.title = "Examiner evidence"
        evidence.explanation = "This exact quote supports the criterion estimate."
        evidence.suggestion = "Confirm against the recording before human approval."
    if evaluation.band_scores.P_confidence < 0.7:
        evaluation.reviewer_flags.append("low_confidence_pronunciation")
    validate_evidence_against_responses(evaluation, responses)
    return evaluation


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {408, 409, 425, 429} or exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


def _without_completed_evaluation(scores: Any) -> dict[str, Any]:
    """Keep progress metadata without presenting a stale evaluation as complete."""
    if not isinstance(scores, dict):
        return {}
    return {
        key: value
        for key, value in scores.items()
        if key not in _COMPLETED_EVALUATION_KEYS
    }


async def _evaluate_full_attempt(
    review_id: UUID,
    review: dict[str, Any],
    attempt: dict[str, Any],
) -> bool:
    responses = repo.list_speaking_responses(attempt_id=UUID(str(attempt["id"])))
    if not responses or any(
        str(row.get("transcription_status")) != "completed" for row in responses
    ):
        return False
    settings = get_settings()
    providers = [] if settings.speaking_eval_stub else get_eval_provider_chain()
    if not settings.speaking_eval_stub and not providers:
        raise RuntimeError("No Speaking evaluation provider is configured")
    provider_name = (
        PROVIDER_NAME_STUB
        if settings.speaking_eval_stub
        else "->".join(provider.name for provider in providers)
    )
    provider_model = (
        PROVIDER_NAME_STUB
        if settings.speaking_eval_stub
        else "->".join(provider.model for provider in providers)
    )
    manifest = attempt.get("speaking_manifest") or []
    inputs, metrics, fingerprint = _attempt_inputs(
        review,
        responses,
        manifest,
        provider_name=provider_name,
        provider_model=provider_model,
    )
    lease_token = uuid4()
    claimed = repo.claim_speaking_attempt_evaluation(
        review_id=review_id,
        fingerprint=fingerprint,
        lease_token=lease_token,
        lease_seconds=EVALUATION_LEASE_SECONDS,
    )
    if claimed is None:
        return True
    attempts = int(claimed.get("evaluation_attempts") or 1)
    transcript = "\n\n".join(
        f"[response_id={item['response_id']} question_id={item['question_id']} "
        f"part={item['part']}]\n{item['transcript']}"
        for item in inputs
    )
    meaningful_total = attempt_meaningful_word_count(inputs)
    try:
        if not is_sufficient_attempt_speech(inputs):
            scores = build_insufficient_speech_scores(
                metrics=metrics,
                fingerprint=fingerprint,
                meaningful_word_count=meaningful_total,
            )
            repo.complete_speaking_attempt_evaluation(
                review_id=review_id,
                lease_token=lease_token,
                fingerprint=fingerprint,
                transcript=transcript,
                ai_scores=scores,
                completed_at_iso=datetime.now(UTC).isoformat(),
            )
            return True
        if settings.speaking_eval_stub:
            evaluation = _stub_attempt_evaluation(inputs)
            status_value = "ai_stub"
        else:
            last_error: Exception | None = None
            selected_provider = None
            claude_budget = check_claude_budget()
            groq_budget = check_groq_budget()
            circuit = is_claude_circuit_open()
            skip_claude = (not claude_budget.ok) or circuit.open
            skip_groq = not groq_budget.ok
            for provider in providers:
                if (
                    provider.name == PROVIDER_NAME_ANTHROPIC_CLAUDE
                    and skip_claude
                ):
                    logger.warning(
                        "Skipping Speaking Claude: %s",
                        claude_budget.reason or circuit.reason or "budget/circuit",
                    )
                    continue
                if provider.name == PROVIDER_NAME_GROQ and skip_groq:
                    logger.warning(
                        "Skipping Speaking Groq: %s",
                        groq_budget.reason or "budget",
                    )
                    continue
                try:
                    if provider.name == PROVIDER_NAME_ANTHROPIC_CLAUDE:
                        consume_claude_eval()
                    elif provider.name == PROVIDER_NAME_GROQ:
                        consume_groq_eval()
                    evaluation = await provider.evaluate_attempt(
                        responses=inputs, fluency_metrics=metrics
                    )
                    selected_provider = provider
                    break
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "Speaking evaluation failed with %s; trying fallback",
                        provider.name,
                        exc_info=exc,
                    )
            if selected_provider is None:
                if settings.ai_budget_fallback_stub and (
                    skip_claude or skip_groq or not providers
                ):
                    evaluation = _stub_attempt_evaluation(inputs)
                    status_value = "ai_stub"
                    provider_name = PROVIDER_NAME_STUB
                    provider_model = PROVIDER_NAME_STUB
                elif last_error is not None:
                    raise last_error
                else:
                    raise RuntimeError("No Speaking evaluation provider completed")
            else:
                provider_name = selected_provider.name
                provider_model = selected_provider.model
                status_value = "ai_complete"
        _apply_pronunciation_advisory(evaluation)
        criteria = evaluation_to_admin_criteria(evaluation)
        scores = {
            "status": status_value,
            "ai_band": evaluation.band_scores.overall,
            **criteria,
            "provider_eval": provider_name,
            "model_eval": provider_model,
            "provider_version": PROVIDER_VERSION,
            "prompt_version": PROMPT_VERSION,
            "evaluation_input_fingerprint": fingerprint,
            "evaluation": evaluation.model_dump(),
            **metrics,
        }
        repo.complete_speaking_attempt_evaluation(
            review_id=review_id,
            lease_token=lease_token,
            fingerprint=fingerprint,
            transcript=transcript,
            ai_scores=scores,
            completed_at_iso=datetime.now(UTC).isoformat(),
        )
    except Exception as exc:
        retryable = attempts < EVALUATION_MAX_ATTEMPTS and _retryable(exc)
        next_attempt = (
            datetime.now(UTC)
            + timedelta(
                seconds=EVALUATION_BACKOFF_SECONDS[
                    min(attempts, len(EVALUATION_BACKOFF_SECONDS)) - 1
                ]
            )
            if retryable
            else None
        )
        repo.fail_speaking_attempt_evaluation(
            review_id=review_id,
            lease_token=lease_token,
            retryable=retryable,
            error=f"{type(exc).__name__}: {exc}",
            next_attempt_at_iso=next_attempt.isoformat() if next_attempt else None,
            ai_scores={
                **_without_completed_evaluation(review.get("ai_scores")),
                **metrics,
                "status": "ai_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "evaluation_input_fingerprint": fingerprint,
            },
        )
        logger.exception("Full-attempt Speaking evaluation failed for %s", review_id)
    return True


async def process_speaking_review_async(review_id: UUID) -> None:
    """Async entry point for request workers already running an event loop."""
    settings = get_settings()
    review = repo.get_speaking_review_by_id(review_id)
    if not review:
        logger.warning("Speaking review %s not found for evaluation", review_id)
        return

    existing_scores = review.get("ai_scores") or {}
    meta = review.get("submission_meta") or {}
    part = int(meta.get("part") or 1)
    duration_sec = meta.get("duration_sec")
    duration_sec = int(duration_sec) if duration_sec is not None else None
    audio_key = str(review.get("audio_url") or "")
    attempt_id = UUID(str(review["attempt_id"]))

    attempt = repo.get_attempt(attempt_id)
    meta_responses = meta.get("responses")
    if isinstance(meta_responses, list) and meta_responses:
        await _evaluate_full_attempt(review_id, review, attempt)
        return
    if isinstance(existing_scores, dict) and existing_scores.get("status") in (
        "ai_complete",
        "ai_stub",
        "insufficient_speech",
    ):
        return
    mock_test_id = UUID(str(attempt["mock_test_id"]))
    question_rows = repo.list_questions_for_part(mock_test_id=mock_test_id, part=part)
    prompts = [str(q.get("prompt") or "") for q in question_rows if q.get("prompt")]
    questions_asked = max(1, len(prompts))

    try:
        if settings.speaking_eval_stub:
            transcript = (
                "I come from a small city and I really enjoy living there because "
                "it is peaceful and the people are friendly."
            )
            words = [
                {"word": "I", "start": 0.0, "end": 0.1},
                {"word": "come", "start": 0.12, "end": 0.4},
                {"word": "from", "start": 0.42, "end": 0.6},
            ]
            metrics = compute_fluency_metrics(
                words=words,
                duration_sec=duration_sec or 3,
                response_count=1,
                questions_asked=questions_asked,
            )
            evaluation = build_stub_evaluation(transcript=transcript, part=part)
            ai_scores = _normalize_ai_scores(
                status="ai_stub",
                transcript=transcript,
                words=words,
                fluency_metrics=metrics,
                evaluation=evaluation,
                provider_asr=PROVIDER_NAME_STUB,
                provider_eval=PROVIDER_NAME_STUB,
                model_asr=PROVIDER_NAME_STUB,
                model_eval=PROVIDER_NAME_STUB,
            )
            repo.update_speaking_review_evaluation(
                review_id=review_id,
                transcript=transcript,
                ai_scores=ai_scores,
            )
            return

        asr = get_asr_provider()
        eval_providers = get_eval_provider_chain()

        if not asr.configured() or not eval_providers:
            raise RuntimeError(
                f"ASR ({settings.asr_provider}) and LLM ({settings.llm_provider}) "
                "providers must be configured for live evaluation"
            )

        if not audio_key:
            raise RuntimeError("Review has no audio_url")

        audio_bytes = get_object_bytes(key=audio_key)
        filename = _filename_from_key(audio_key)
        asr_result = await asr.transcribe(audio_bytes=audio_bytes, filename=filename)
        transcript = str(asr_result.get("text") or "").strip()
        words = list(asr_result.get("words") or [])
        if meaningful_word_count(transcript) < MIN_MEANINGFUL_WORDS_RESPONSE:
            metrics = compute_fluency_metrics(
                words=words,
                duration_sec=duration_sec,
                response_count=1,
                questions_asked=questions_asked,
                transcript=transcript,
            )
            scores = build_insufficient_speech_scores(
                metrics={"attempt_metrics": metrics, "fluency_metrics": metrics},
                fingerprint="legacy-single-audio",
                meaningful_word_count=meaningful_word_count(transcript),
            )
            repo.update_speaking_review_evaluation(
                review_id=review_id,
                transcript=transcript or None,
                ai_scores=scores,
            )
            return

        metrics = compute_fluency_metrics(
            words=words,
            duration_sec=duration_sec,
            response_count=1,
            questions_asked=questions_asked,
            transcript=transcript,
        )
        last_error: Exception | None = None
        eval_provider = None
        for candidate in eval_providers:
            try:
                evaluation = await candidate.evaluate(
                    transcript=transcript,
                    fluency_metrics=metrics,
                    prompts=prompts,
                    part=part,
                )
                eval_provider = candidate
                break
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Speaking evaluation failed with %s; trying fallback",
                    candidate.name,
                    exc_info=exc,
                )
        if eval_provider is None:
            if last_error is not None:
                raise last_error
            raise RuntimeError("No Speaking evaluation provider completed")
        ai_scores = _normalize_ai_scores(
            status="ai_complete",
            transcript=transcript,
            words=words,
            fluency_metrics=metrics,
            evaluation=evaluation,
            provider_asr=asr.name,
            provider_eval=eval_provider.name,
            model_asr=asr.model,
            model_eval=eval_provider.model,
        )
        repo.update_speaking_review_evaluation(
            review_id=review_id,
            transcript=transcript,
            ai_scores=ai_scores,
        )
    except Exception as exc:
        logger.exception("Speaking evaluation failed for review %s", review_id)
        failed_scores = {
            **(existing_scores if isinstance(existing_scores, dict) else {}),
            "status": "ai_failed",
            "error": str(exc),
        }
        repo.update_speaking_review_evaluation(
            review_id=review_id,
            transcript=review.get("transcript"),
            ai_scores=failed_scores,
        )


def process_speaking_review(review_id: UUID) -> None:
    """Sync entry point for FastAPI BackgroundTasks and schedulers."""
    asyncio.run(process_speaking_review_async(review_id))
