"""Listening module constants — IELTS-specific."""

from __future__ import annotations

from app.mock_catalog.constants import M01_MOCK_TEST_ID

# Canonical full mock (all listening parts live under one mock_tests row)
LISTENING_TEST_ID = M01_MOCK_TEST_ID

# Legacy aliases (redirect / compat)
LISTENING_S2_TEST_ID = LISTENING_TEST_ID
LISTENING_S3_TEST_ID = LISTENING_TEST_ID
LISTENING_S4_TEST_ID = LISTENING_TEST_ID

PUBLISHED_LISTENING_TEST_IDS: tuple[str, ...] = (M01_MOCK_TEST_ID,)

LISTENING_DURATION_MINUTES = 30
LISTENING_GRACE_SECONDS = 120
LISTENING_AUDIO_PRESIGN_EXPIRY_SECONDS = 10800  # 3 hours

LISTENING_QUESTION_COUNT_TARGET = 40

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
