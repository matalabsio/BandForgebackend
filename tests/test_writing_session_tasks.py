"""Writing pending/review session_tasks for dual-task mocks."""

from unittest.mock import patch
from uuid import UUID

from app.writing.service import get_pending_status, get_review

USER = UUID("00000000-0000-4000-8000-000000000099")
ATTEMPT_T2 = UUID("00000000-0000-4000-8000-000000000088")
ATTEMPT_T1 = UUID("00000000-0000-4000-8000-000000000087")
MOCK_ATTEMPT = UUID("00000000-0000-4000-8000-000000000066")
MOCK_TEST = UUID("a0000000-0000-4000-8000-000000000001")
QUESTION = UUID("00000000-0000-4000-8000-000000000077")


def test_pending_returns_session_tasks_for_mock():
    attempt = {
        "id": str(ATTEMPT_T2),
        "user_id": str(USER),
        "mock_test_id": "a0000000-0000-4000-8000-000000000001",
        "module": "writing",
        "status": "completed",
        "part": 2,
        "mock_attempt_id": str(MOCK_ATTEMPT),
        "completed_at": "2026-05-27T12:00:00+00:00",
    }
    session_rows = [
        {"id": str(ATTEMPT_T1), "part": 1, "status": "completed"},
        {"id": str(ATTEMPT_T2), "part": 2, "status": "completed"},
    ]

    def fake_review(aid: UUID):
        if aid == ATTEMPT_T1:
            return {"status": "pending", "human_band": None}
        return {"status": "pending", "human_band": None}

    with (
        patch("app.writing.service.repo.get_attempt", return_value=attempt),
        patch(
            "app.writing.service.repo.get_writing_review_for_attempt",
            side_effect=fake_review,
        ),
        patch(
            "app.writing.service.repo.list_completed_writing_attempts_for_session",
            return_value=session_rows,
        ),
    ):
        res = get_pending_status(attempt_id=ATTEMPT_T2, user_id=USER)

    assert len(res.session_tasks) == 2
    assert res.session_tasks[0].part == 1
    assert res.session_tasks[0].attempt_id == ATTEMPT_T1
    assert res.session_tasks[1].part == 2
    assert res.session_tasks[1].attempt_id == ATTEMPT_T2


def test_get_review_uses_cached_ai_band_without_blocking_eval():
    attempt = {
        "id": str(ATTEMPT_T2),
        "user_id": str(USER),
        "mock_test_id": str(MOCK_TEST),
        "module": "writing",
        "status": "completed",
        "part": 2,
        "mock_attempt_id": str(MOCK_ATTEMPT),
        "completed_at": "2026-05-27T12:00:00+00:00",
    }
    question = {
        "id": str(QUESTION),
        "prompt": "Discuss both views and give your opinion.",
        "question_type": "task2",
        "part": 2,
        "options": {"min_words": 250},
    }
    review_row = {
        "id": str(UUID("00000000-0000-4000-8000-000000000099")),
        "status": "pending",
        "human_band": None,
        "created_at": "2026-05-27T12:00:00+00:00",
        "ai_scores": {
            "status": "ai_complete",
            "ai_band": 6.5,
            "criteria": {
                "task_achievement": 6.5,
                "coherence": 6.0,
                "lexical_resource": 6.5,
                "grammar": 6.0,
            },
            "strengths": ["Clear position"],
            "improvements": ["Add more specific examples"],
            "model_name": "llama-3.3-70b-versatile",
            "word_count_estimate": 5.5,
        },
    }

    with (
        patch("app.writing.service.repo.get_attempt", return_value=attempt),
        patch("app.writing.service.repo.list_questions_for_part", return_value=[question]),
        patch(
            "app.writing.service.repo.get_answer_for_attempt",
            return_value={"user_answer": " ".join(["word"] * 260)},
        ),
        patch(
            "app.writing.service.repo.get_mock_test",
            return_value={"id": str(MOCK_TEST), "title": "Mock 1", "is_published": True},
        ),
        patch("app.writing.service.repo.get_writing_review_for_attempt", return_value=review_row),
        patch("app.writing.service.repo.get_module_score", return_value=None),
        patch("app.writing.service.ai_evaluation_available", return_value=True),
        patch("app.writing.service.run_writing_evaluation") as run_eval,
        patch("app.writing.service.threading.Thread") as thread_cls,
        patch(
            "app.writing.service.repo.list_completed_writing_attempts_for_session",
            return_value=[],
        ),
    ):
        res = get_review(attempt_id=ATTEMPT_T2, user_id=USER)

    run_eval.assert_not_called()
    thread_cls.assert_not_called()
    assert res.band == 6.5
    assert res.ai_band == 6.5
    assert res.ai_status == "ai_complete"
    assert res.band_source == "ai"
    assert res.ai_model_name == "llama-3.3-70b-versatile"
    assert "Clear position" in res.ai_strengths
    assert res.human_verified is False


def test_get_review_human_verified_and_notes():
    attempt = {
        "id": str(ATTEMPT_T2),
        "user_id": str(USER),
        "mock_test_id": str(MOCK_TEST),
        "module": "writing",
        "status": "completed",
        "part": 2,
        "mock_attempt_id": str(MOCK_ATTEMPT),
        "completed_at": "2026-05-27T12:00:00+00:00",
    }
    question = {
        "id": str(QUESTION),
        "prompt": "Discuss both views.",
        "question_type": "task2",
        "part": 2,
        "options": {"min_words": 250},
    }
    review_row = {
        "id": str(UUID("00000000-0000-4000-8000-000000000099")),
        "status": "completed",
        "human_band": 7.0,
        "reviewer_notes": "Strong argumentation.",
        "ai_scores": {"ai_band": 6.5, "criteria": {"task_achievement": 6.5}},
    }

    with (
        patch("app.writing.service.repo.get_attempt", return_value=attempt),
        patch("app.writing.service.repo.list_questions_for_part", return_value=[question]),
        patch(
            "app.writing.service.repo.get_answer_for_attempt",
            return_value={"user_answer": " ".join(["word"] * 260)},
        ),
        patch(
            "app.writing.service.repo.get_mock_test",
            return_value={"id": str(MOCK_TEST), "title": "Mock 1", "is_published": True},
        ),
        patch("app.writing.service.repo.get_writing_review_for_attempt", return_value=review_row),
        patch("app.writing.service.repo.get_module_score", return_value=None),
        patch("app.writing.service.ai_evaluation_available", return_value=False),
        patch(
            "app.writing.service.repo.list_completed_writing_attempts_for_session",
            return_value=[],
        ),
    ):
        res = get_review(attempt_id=ATTEMPT_T2, user_id=USER)

    assert res.band == 7.0
    assert res.band_source == "human"
    assert res.human_verified is True
    assert res.reviewer_notes == "Strong argumentation."
