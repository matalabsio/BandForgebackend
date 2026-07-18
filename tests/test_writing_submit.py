"""Writing submit queues human review instead of persisting an immediate band."""

from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import HTTPException

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


def test_submit_queues_review_without_module_score():
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
    essay = " ".join(["word"] * 260)
    mock_test = {"id": str(M01), "title": "Mock 1", "is_published": True}

    with (
        patch("app.writing.service.repo.get_attempt", return_value=attempt),
        patch(
            "app.writing.service.repo.list_questions_for_part",
            return_value=[question],
        ),
        patch("app.writing.service.repo.get_mock_test", return_value=mock_test),
        patch("app.writing.service.repo.upsert_answer") as upsert,
        patch(
            "app.writing.service.repo.insert_writing_review",
            return_value={"id": "00000000-0000-4000-8000-000000000055"},
        ) as insert_review,
        patch(
            "app.writing.service.repo.mark_attempt_completed",
            return_value={"completed_at": "2026-05-27T12:00:00+00:00"},
        ) as complete,
        patch("app.writing.service.run_writing_evaluation") as run_eval,
    ):
        res = submit_attempt(
            attempt_id=ATTEMPT,
            user_id=USER,
            answers=[{"question_id": str(QUESTION), "user_answer": essay}],
        )

    upsert.assert_called_once()
    insert_review.assert_called_once()
    ai_scores = insert_review.call_args.kwargs["ai_scores"]
    assert ai_scores["status"] == "pending"
    run_eval.assert_called_once()
    complete.assert_called_once()
    assert res.status == "completed"
    assert res.saved_for_review is True
    assert res.word_count == 260
    assert res.band is None
    assert res.min_words == 250
    assert res.part == 2
