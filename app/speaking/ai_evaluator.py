"""Thin public API for Speaking AI evaluation (mirrors writing ai_evaluator)."""

from __future__ import annotations

import logging
from uuid import UUID

from app.config import get_settings
from app.speaking.providers.factory import asr_configured, eval_configured
from app.speaking.speaking_evaluator import (
    process_speaking_review,
    process_speaking_review_async,
)

logger = logging.getLogger(__name__)


def ai_evaluation_available() -> bool:
    settings = get_settings()
    if settings.speaking_eval_stub:
        return True
    return asr_configured() and eval_configured()


async def run_speaking_evaluation_async(review_id: UUID) -> None:
    """Run evaluation in the caller's event loop; never raise to callers."""
    try:
        await process_speaking_review_async(review_id)
    except Exception:
        logger.exception("Async Speaking evaluation failed for review %s", review_id)


def run_speaking_evaluation(review_id: UUID) -> None:
    """Sync entry point for FastAPI BackgroundTasks and schedulers."""
    try:
        process_speaking_review(review_id)
    except Exception:
        logger.exception("Speaking evaluation failed for review %s", review_id)
