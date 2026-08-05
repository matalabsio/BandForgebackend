"""Reading scoring — reuses shared objective answer checking."""

from __future__ import annotations

from app.reading.constants import READING_BAND_TABLE
from app.scoring.answers import (
    build_skill_breakdown,
    is_answer_correct,
    score_answers,
)


def calculate_reading_band(raw_score: int, total: int = 40) -> float:
    """Scale partial tests to 40-equivalent, then map via Academic Reading table."""
    safe_total = max(1, int(total))
    scaled = round((raw_score / safe_total) * 40) if safe_total != 40 else int(raw_score)
    scaled = max(0, min(40, scaled))
    for threshold, band in READING_BAND_TABLE:
        if scaled >= threshold:
            return float(band)
    return 0.0


__all__ = [
    "build_skill_breakdown",
    "calculate_reading_band",
    "is_answer_correct",
    "score_answers",
]
