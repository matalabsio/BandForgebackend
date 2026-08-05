"""Synchronous MCQ scoring + IELTS Listening band + skill breakdown.

Pure functions: no DB calls. Answer equality lives in ``app.scoring``.
"""

from __future__ import annotations

from app.listening.constants import LISTENING_BAND_TABLE
from app.scoring.answers import (
    build_skill_breakdown,
    is_answer_correct,
    normalize_answer,
    score_answers,
)

# Back-compat alias used by older tests / imports.
_normalize = normalize_answer


def calculate_band(raw_score: int, total: int = 40) -> float:
    """Convert raw MCQ-correct count to an IELTS Listening band.

    The constant table assumes a 40-question test; tests with fewer
    questions are scaled to a 40-equivalent before lookup so band ranges
    stay meaningful for partial seeds.
    """
    safe_total = max(1, int(total))
    scaled = round((raw_score / safe_total) * 40) if safe_total != 40 else int(raw_score)
    scaled = max(0, min(40, scaled))
    for threshold, band in LISTENING_BAND_TABLE:
        if scaled >= threshold:
            return float(band)
    return 0.0


__all__ = [
    "_normalize",
    "build_skill_breakdown",
    "calculate_band",
    "is_answer_correct",
    "normalize_answer",
    "score_answers",
]
