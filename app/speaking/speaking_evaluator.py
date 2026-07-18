"""Orchestrates Speaking Phase C: ASR -> metrics -> LLM eval -> persist."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from app.config import get_settings
from app.speaking import repository as repo
from app.speaking.evaluation_schemas import (
    SpeakingEvaluation,
    build_stub_evaluation,
    evaluation_to_admin_criteria,
)
from app.speaking.fluency_metrics import compute_fluency_metrics
from app.speaking.providers.constants import (
    PROVIDER_NAME_STUB,
    PROVIDER_VERSION,
)
from app.speaking.providers.factory import get_asr_provider, get_eval_provider
from app.speaking.speaking_prompt import PROMPT_VERSION
from app.storage.r2 import get_object_bytes

logger = logging.getLogger(__name__)


def _filename_from_key(audio_key: str) -> str:
    name = audio_key.rsplit("/", 1)[-1]
    return name if "." in name else "recording.webm"


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


async def _evaluate_review_async(review_id: UUID) -> None:
    settings = get_settings()
    review = repo.get_speaking_review_by_id(review_id)
    if not review:
        logger.warning("Speaking review %s not found for evaluation", review_id)
        return

    existing_scores = review.get("ai_scores") or {}
    if isinstance(existing_scores, dict) and existing_scores.get("status") in (
        "ai_complete",
        "ai_stub",
    ):
        return

    meta = review.get("submission_meta") or {}
    part = int(meta.get("part") or 1)
    duration_sec = meta.get("duration_sec")
    duration_sec = int(duration_sec) if duration_sec is not None else None
    audio_key = str(review.get("audio_url") or "")
    attempt_id = UUID(str(review["attempt_id"]))

    attempt = repo.get_attempt(attempt_id)
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
        eval_provider = get_eval_provider()

        if not asr.configured() or not eval_provider.configured():
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
        if not transcript:
            raise RuntimeError("ASR returned an empty transcript")

        metrics = compute_fluency_metrics(
            words=words,
            duration_sec=duration_sec,
            response_count=1,
            questions_asked=questions_asked,
        )
        evaluation = await eval_provider.evaluate(
            transcript=transcript,
            fluency_metrics=metrics,
            prompts=prompts,
            part=part,
        )
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
    """Sync entry point for FastAPI BackgroundTasks."""
    asyncio.run(_evaluate_review_async(review_id))
