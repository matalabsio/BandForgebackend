"""AI evaluation for mock writing essays (stub / Claude primary / Groq fallback)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from app.config import get_settings
from app.diagnostic.evaluation_schemas import evaluation_to_ai_scores
from app.writing import repository as repo
from app.writing.eval_cache import (
    EVALUATION_SOURCE_AI,
    EVALUATION_SOURCE_STUB,
    cache_attempt_id_for_hash,
    lookup_cached_evaluation,
    persist_evaluation,
    row_to_evaluation_response,
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

AI_STATUS_PENDING = "pending"
AI_STATUS_COMPLETE = "ai_complete"
AI_STATUS_STUB = "ai_stub"
AI_STATUS_FAILED = "ai_failed"
_TERMINAL_AI_STATUSES = frozenset({AI_STATUS_COMPLETE, AI_STATUS_STUB})


def ai_evaluation_available() -> bool:
    settings = get_settings()
    if settings.writing_eval_stub:
        return True
    return writing_eval_configured()


async def evaluate_mock_essay(
    *,
    part: int,
    question: str,
    essay: str,
    visual_description: str | None = None,
    target_band: float | None = None,
) -> dict[str, Any] | None:
    """Return an AI band + criteria + feedback for one essay, or None on failure.

    Never raises — the module review must still render (with the word-count
    estimate) if AI evaluation is unavailable or times out.
    """
    cleaned = sanitize_essay(essay, question)
    words = word_count(cleaned)
    if words < MIN_WORDS_FOR_AI:
        return None
    if not ai_evaluation_available():
        return None

    visual = (visual_description or "").strip()
    essay_hash = compute_essay_hash(
        task_part=part,
        question=question,
        essay=cleaned,
        prompt_version=resolve_prompt_version(),
        model_name=writing_cache_model_key(),
        visual_description=visual,
    )
    cached = lookup_cached_evaluation(essay_hash)
    if cached:
        evaluation = row_to_evaluation_response(cached)
        if evaluation is not None:
            logger.info(
                "Mock writing cache hit (essay_hash=%s…, id=%s)",
                essay_hash[:8],
                cached.get("id"),
            )
            model_name = str(cached.get("model_name") or "cached")
            raw = cached.get("raw_ai_response")
            provider_used = "cached"
            if isinstance(raw, dict) and raw.get("provider_used"):
                provider_used = str(raw["provider_used"])
            return evaluation_to_ai_scores(
                evaluation,
                model_name=model_name,
                provider_used=provider_used,
            )

    try:
        result = await evaluate_writing_essay(
            task_part=part,
            question=question,
            essay=cleaned,
            visual_description=visual or None,
            target_band=target_band,
        )
    except Exception:
        logger.exception("Mock writing AI evaluation failed (part=%s)", part)
        return None

    evaluation_source = (
        EVALUATION_SOURCE_STUB
        if get_settings().writing_eval_stub
        else EVALUATION_SOURCE_AI
    )
    try:
        persist_evaluation(
            client_attempt_id=cache_attempt_id_for_hash(essay_hash),
            essay_hash=essay_hash,
            task_part=part,
            question=question,
            original_essay=essay.strip(),
            cleaned_essay=cleaned,
            evaluation=result.evaluation,
            words=words,
            sentences=count_sentences(cleaned),
            paragraphs=count_paragraphs(cleaned),
            raw_ai_response=result.raw_store,
            prompt_version=result.prompt_version,
            model_name=result.model_name,
            evaluation_source=evaluation_source,
        )
    except Exception:
        logger.exception("Mock writing evaluation cache persist failed (part=%s)", part)

    return evaluation_to_ai_scores(
        result.evaluation,
        model_name=result.model_name,
        provider_used=result.provider_used,
    )


async def _evaluate_review_async(review_id: UUID) -> None:
    review = repo.get_writing_review_by_id(review_id)
    if not review:
        logger.warning("Writing review %s not found for evaluation", review_id)
        return

    existing_scores = review.get("ai_scores") or {}
    if not isinstance(existing_scores, dict):
        existing_scores = {}
    if existing_scores.get("status") in _TERMINAL_AI_STATUSES:
        return

    meta = review.get("submission_meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    part = int(meta.get("part") or 1)
    question = str(meta.get("question") or "")
    essay = str(meta.get("essay") or "").strip()
    visual_description = str(meta.get("visual_description") or "").strip()
    raw_target = meta.get("target_band")
    target_band: float | None = None
    if raw_target is not None:
        try:
            target_band = float(raw_target)
        except (TypeError, ValueError):
            target_band = None

    if not essay:
        failed = {
            **existing_scores,
            "status": AI_STATUS_FAILED,
            "error": "Review has no essay text",
        }
        repo.update_writing_review_ai_scores(review_id=review_id, ai_scores=failed)
        return

    try:
        evaluation = await evaluate_mock_essay(
            part=part,
            question=question,
            essay=essay,
            visual_description=visual_description or None,
            target_band=target_band,
        )
        if evaluation is None:
            raise RuntimeError(
                "Writing AI evaluation returned no result "
                "(essay too short, provider unavailable, or call failed)"
            )
        status = (
            AI_STATUS_STUB
            if get_settings().writing_eval_stub
            else AI_STATUS_COMPLETE
        )
        merged = {
            **existing_scores,
            **evaluation,
            "status": status,
            "error": None,
        }
        repo.update_writing_review_ai_scores(review_id=review_id, ai_scores=merged)
    except Exception as exc:
        logger.exception("Writing evaluation failed for review %s", review_id)
        failed = {
            **existing_scores,
            "status": AI_STATUS_FAILED,
            "error": str(exc),
        }
        repo.update_writing_review_ai_scores(review_id=review_id, ai_scores=failed)


def run_writing_evaluation(review_id: UUID) -> None:
    """Sync entry for FastAPI BackgroundTasks; never raises to callers."""
    try:
        asyncio.run(_evaluate_review_async(review_id))
    except Exception:
        logger.exception("run_writing_evaluation failed for review %s", review_id)
