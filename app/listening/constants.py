"""Listening module constants — IELTS-specific."""

from __future__ import annotations

# Single live listening test (founder Greenfield Part 1). Admin UI will manage many later.
LISTENING_TEST_ID = "d0000000-0000-4000-8000-000000000001"

LISTENING_DURATION_MINUTES = 30
LISTENING_GRACE_SECONDS = 120
LISTENING_AUDIO_PRESIGN_EXPIRY_SECONDS = 10800  # 3 hours

LISTENING_QUESTION_COUNT_TARGET = 40

# IELTS Academic Listening raw-score to band conversion.
# Source: standard IELTS Listening table (raw out of 40 -> band).
# A short table that always returns a valid band for raw in [0, 40].
LISTENING_BAND_TABLE: tuple[tuple[int, float], ...] = (
    (39, 9.0),
    (37, 8.5),
    (35, 8.0),
    (32, 7.5),
    (30, 7.0),
    (26, 6.5),
    (23, 6.0),
    (18, 5.5),
    (16, 5.0),
    (13, 4.5),
    (11, 4.0),
    (8, 3.5),
    (6, 3.0),
    (4, 2.5),
    (3, 2.0),
    (2, 1.5),
    (1, 1.0),
    (0, 0.0),
)
