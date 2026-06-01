"""Reading module constants — IELTS Academic."""

from __future__ import annotations

from app.mock_catalog.constants import M01_MOCK_TEST_ID

READING_T2_TEST_ID = M01_MOCK_TEST_ID
READING_T3_TEST_ID = M01_MOCK_TEST_ID

PUBLISHED_READING_TEST_IDS: tuple[str, ...] = (M01_MOCK_TEST_ID,)

READING_DURATION_MINUTES = 60
READING_GRACE_SECONDS = 120

READING_BAND_TABLE: tuple[tuple[int, float], ...] = (
    (39, 9.0),
    (37, 8.5),
    (35, 8.0),
    (33, 7.5),
    (30, 7.0),
    (27, 6.5),
    (23, 6.0),
    (19, 5.5),
    (15, 5.0),
    (13, 4.5),
    (10, 4.0),
    (8, 3.5),
    (6, 3.0),
    (4, 2.5),
    (3, 2.0),
    (2, 1.5),
    (1, 1.0),
    (0, 0.0),
)
