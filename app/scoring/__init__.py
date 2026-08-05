"""Objective scoring package (Phase 3)."""

from app.scoring.answers import (
    build_skill_breakdown,
    is_answer_correct,
    normalize_answer,
    score_answers,
)

__all__ = [
    "build_skill_breakdown",
    "is_answer_correct",
    "normalize_answer",
    "score_answers",
]
