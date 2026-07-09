"""Thin public API for Speaking AI evaluation (mirrors writing ai_evaluator)."""

from __future__ import annotations

import logging
from uuid import UUID

from app.config import get_settings
from app.speaking.providers.factory import asr_configured, eval_configured
from app.speaking.speaking_evaluator import process_speaking_review

logger = logging.getLogger(__name__)


def ai_evaluation_available() -> bool:
    settings = get_settings()
    if settings.speaking_eval_stub:
        return True
    return asr_configured() and eval_configured()


def run_speaking_evaluation(review_id: UUID) -> None:
    """Run evaluation pipeline; never raises to callers."""
    try:
        process_speaking_review(review_id)
    except Exception:
        logger.exception("run_speaking_evaluation failed for review %s", review_id)
