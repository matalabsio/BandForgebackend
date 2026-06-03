"""Writing submit scores the essay by word count and persists a band."""

from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.writing.evaluation import calculate_writing_band
from app.writing.service import submit_attempt

M01 = UUID("a0000000-0000-4000-8000-000000000001")
USER = UUID("00000000-0000-4000-8000-000000000099")
ATTEMPT = UUID("00000000-0000-4000-8000-000000000088")
QUESTION = UUID("00000000-0000-4000-8000-000000000077")


def test_submit_rejects_empty_essay():
    attempt = {
        "id": str(ATTEMPT),
        "user_id": str(USER),
        "mock_test_id": str(M01),
        "module": "writing",
        "status": "in_progress",
        "part": 1,
        "mock_attempt_id": None,
    }
    question = {
        "id": str(QUESTION),
        "prompt": "Task",
        "question_type": "task1_academic",
        "part": 1,
    }

    with (
        patch("app.writing.service.repo.get_attempt", return_value=attempt),
        patch(
            "app.writing.service.repo.list_questions_for_part",
            return_value=[question],
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            submit_attempt(
                attempt_id=ATTEMPT,
                user_id=USER,
                answers=[{"question_id": str(QUESTION), "user_answer": "  "}],
            )
        assert exc.value.status_code == 400


def test_submit_persists_word_count_band():
    attempt = {
        "id": str(ATTEMPT),
        "user_id": str(USER),
        "mock_test_id": str(M01),
        "module": "writing",
        "status": "in_progress",
        "part": 2,
        "mock_attempt_id": None,
    }
    question = {
        "id": str(QUESTION),
        "prompt": "Task",
        "question_type": "task2",
        "part": 2,
    }
    essay = " ".join(["word"] * 260)  # over the 250-word Task 2 minimum
    expected_band = calculate_writing_band(words=260, part=2)

    with (
        patch("app.writing.service.repo.get_attempt", return_value=attempt),
        patch(
            "app.writing.service.repo.list_questions_for_part",
            return_value=[question],
        ),
        patch(
            "app.writing.service.persist_module_submit_bundle",
            return_value={"completed_at": "2026-05-27T12:00:00+00:00"},
        ) as persist,
    ):
        res = submit_attempt(
            attempt_id=ATTEMPT,
            user_id=USER,
            answers=[{"question_id": str(QUESTION), "user_answer": essay}],
        )

    persist.assert_called_once()
    _, persist_kwargs = persist.call_args
    assert persist_kwargs["module"] == "writing"
    assert persist_kwargs["raw_score"] == 260
    assert persist_kwargs["band"] == expected_band
    assert res.status == "completed"
    assert res.saved_for_review is False
    assert res.word_count == 260
    assert res.band is not None and res.band >= 7.8
    assert res.min_words == 250
    assert res.part == 2


def test_writing_band_ladder():
    # Task 2 (min 250): at/over minimum lands in the 7.8-8.3 range.
    assert calculate_writing_band(words=250, part=2) == 7.8
    assert calculate_writing_band(words=350, part=2) == 8.3
    assert calculate_writing_band(words=500, part=2) == 8.3  # capped
    # Below the minimum scales down.
    assert calculate_writing_band(words=200, part=2) < 7.8
    assert calculate_writing_band(words=0, part=2) == 0.0
    # Task 1 uses the 150-word minimum.
    assert calculate_writing_band(words=150, part=1) == 7.8
    assert calculate_writing_band(words=100, part=1) < 7.8
