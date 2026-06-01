"""Word-count based band estimate for the Writing module.

This is a heuristic, not a full IELTS rubric evaluation. It rewards responses
that meet the task's minimum word count and scales the band down for
under-length essays. Real Task Achievement / Coherence / Lexical / Grammar
scoring is out of scope here.
"""

from __future__ import annotations

from app.writing.constants import WRITING_MIN_WORDS

# Band awarded when the essay exactly meets the minimum word count.
_BASE_BAND_AT_MINIMUM = 7.8
# Maximum bonus added for comfortably exceeding the minimum.
_MAX_OVER_BONUS = 0.5
# Words above the minimum needed to earn the full bonus (→ 8.3).
_WORDS_FOR_FULL_BONUS = 100
# Floor used when scaling sub-minimum essays toward zero length.
_UNDER_FLOOR_BAND = 3.0


def word_count(text: str) -> int:
    stripped = text.strip()
    return len(stripped.split()) if stripped else 0


def min_words_for_part(part: int) -> int:
    return WRITING_MIN_WORDS.get(part, WRITING_MIN_WORDS[2])


def calculate_writing_band(*, words: int, part: int) -> float:
    """Estimate a writing band from the word count for a task.

    - At or above the minimum (250 for Task 2, 150 for Task 1): 7.8 rising to
      8.3 as the response exceeds the minimum by 100+ words.
    - Below the minimum: linearly scaled down from 7.8 toward 3.0.
    - Empty response: 0.0.
    """
    if words <= 0:
        return 0.0

    minimum = min_words_for_part(part)
    if words >= minimum:
        over = words - minimum
        bonus = min(_MAX_OVER_BONUS, (over / _WORDS_FOR_FULL_BONUS) * _MAX_OVER_BONUS)
        return round(_BASE_BAND_AT_MINIMUM + bonus, 1)

    ratio = words / minimum
    band = _UNDER_FLOOR_BAND + ratio * (_BASE_BAND_AT_MINIMUM - _UNDER_FLOOR_BAND)
    return round(band, 1)
