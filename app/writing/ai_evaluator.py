"""AI (Groq) evaluation for mock writing essays.

Reuses the diagnostic writing Groq pipeline so mock reviews and diagnostics
share one prompt/model. This returns an AI *estimate* shown immediately after
Task 2; a certified examiner band replaces it later on the results page.
"""

from __future__ import annotations

import logging
from typing import Any

from app.diagnostic.evaluation_schemas import criteria_from_evaluation
from app.diagnostic.groq_client import groq_configured
from app.diagnostic.writing_evaluator import (
    MIN_WORDS_FOR_AI,
    _call_groq_evaluation,
    sanitize_essay,
)
from app.writing.evaluation import word_count

logger = logging.getLogger(__name__)


def ai_evaluation_available() -> bool:
    return groq_configured()


async def evaluate_mock_essay(
    *,
    part: int,
    question: str,
    essay: str,
) -> dict[str, Any] | None:
    """Return an AI band + criteria + feedback for one essay, or None on failure.

    Never raises — the module review must still render (with the word-count
    estimate) if AI evaluation is unavailable or times out.
    """
    cleaned = sanitize_essay(essay, question)
    if word_count(cleaned) < MIN_WORDS_FOR_AI:
        return None
    if not ai_evaluation_available():
        return None

    try:
        evaluation, _raw, _prompt_version, model_name = await _call_groq_evaluation(
            task_part=part,
            question=question,
            essay=cleaned,
        )
    except Exception:
        logger.exception("Mock writing AI evaluation failed (part=%s)", part)
        return None

    return {
        "ai_band": evaluation.overall_band,
        "criteria": criteria_from_evaluation(evaluation),
        "strengths": list(evaluation.strengths),
        "improvements": [*evaluation.weaknesses, *evaluation.improvement_tips],
        "model_name": model_name,
    }
