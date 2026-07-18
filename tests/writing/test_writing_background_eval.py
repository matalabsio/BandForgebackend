"""Tests for writing submit → background AI evaluation + pending ai_status."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from app.writing.ai_evaluator import (
    AI_STATUS_COMPLETE,
    AI_STATUS_PENDING,
    AI_STATUS_STUB,
    run_writing_evaluation,
)
from app.writing.service import get_pending_status, get_review, submit_attempt

M01 = UUID("a0000000-0000-4000-8000-000000000001")
USER = UUID("00000000-0000-4000-8000-000000000099")
ATTEMPT = UUID("00000000-0000-4000-8000-000000000088")
QUESTION = UUID("00000000-0000-4000-8000-000000000077")
REVIEW = UUID("00000000-0000-4000-8000-000000000066")


def _attempt(**overrides):
    base = {
        "id": str(ATTEMPT),
        "user_id": str(USER),
        "mock_test_id": str(M01),
        "module": "writing",
        "status": "completed",
        "part": 2,
        "mock_attempt_id": None,
        "completed_at": "2026-05-27T12:00:00+00:00",
    }
    base.update(overrides)
    return base


def _question():
    return {
        "id": str(QUESTION),
        "prompt": "Discuss both views.",
        "question_type": "task2",
        "part": 2,
        "options": None,
    }


def test_submit_sets_pending_status_and_enqueues_background_eval():
    attempt = _attempt(status="in_progress")
    essay = " ".join(["word"] * 260)
    mock_test = {"id": str(M01), "title": "Mock 1", "is_published": True}
    review_row = {"id": str(REVIEW)}
    bg = MagicMock()

    with (
        patch("app.writing.service.repo.get_attempt", return_value=attempt),
        patch(
            "app.writing.service.repo.list_questions_for_part",
            return_value=[_question()],
        ),
        patch("app.writing.service.repo.get_mock_test", return_value=mock_test),
        patch("app.writing.service.repo.upsert_answer"),
        patch(
            "app.writing.service.repo.insert_writing_review",
            return_value=review_row,
        ) as insert_review,
        patch(
            "app.writing.service.repo.mark_attempt_completed",
            return_value={"completed_at": "2026-05-27T12:00:00+00:00"},
        ),
    ):
        res = submit_attempt(
            attempt_id=ATTEMPT,
            user_id=USER,
            answers=[{"question_id": str(QUESTION), "user_answer": essay}],
            background_tasks=bg,
        )

    insert_review.assert_called_once()
    ai_scores = insert_review.call_args.kwargs["ai_scores"]
    assert ai_scores["status"] == AI_STATUS_PENDING
    assert "word_count_estimate" in ai_scores
    bg.add_task.assert_called_once()
    assert bg.add_task.call_args.args[0] is run_writing_evaluation
    assert bg.add_task.call_args.args[1] == REVIEW
    assert res.saved_for_review is True
    assert res.band is None


def test_run_writing_evaluation_persists_stub_status():
    review = {
        "id": str(REVIEW),
        "ai_scores": {"status": AI_STATUS_PENDING, "word_count": 200},
        "submission_meta": {
            "part": 2,
            "question": "Discuss both views.",
            "essay": " ".join(["word"] * 120),
        },
    }
    evaluation = {
        "ai_band": 6.0,
        "criteria": {
            "task_achievement": 6.0,
            "coherence": 6.0,
            "lexical_resource": 6.0,
            "grammar": 5.5,
        },
        "strengths": ["Clear position"],
        "improvements": ["Add examples"],
        "model_name": "stub",
        "provider_used": "stub",
    }

    with (
        patch(
            "app.writing.ai_evaluator.repo.get_writing_review_by_id",
            return_value=review,
        ),
        patch(
            "app.writing.ai_evaluator.evaluate_mock_essay",
            new_callable=AsyncMock,
            return_value=evaluation,
        ),
        patch("app.writing.ai_evaluator.get_settings") as settings,
        patch(
            "app.writing.ai_evaluator.repo.update_writing_review_ai_scores"
        ) as update,
    ):
        settings.return_value.writing_eval_stub = True
        run_writing_evaluation(REVIEW)

    update.assert_called_once()
    saved = update.call_args.kwargs["ai_scores"]
    assert saved["status"] == AI_STATUS_STUB
    assert saved["ai_band"] == 6.0


def test_get_pending_status_exposes_ai_fields():
    attempt = _attempt()
    review = {
        "id": str(REVIEW),
        "status": "pending",
        "human_band": None,
        "ai_scores": {
            "status": AI_STATUS_COMPLETE,
            "ai_band": 6.5,
        },
        "created_at": datetime.now(UTC).isoformat(),
    }

    with (
        patch("app.writing.service.repo.get_attempt", return_value=attempt),
        patch(
            "app.writing.service.repo.get_writing_review_for_attempt",
            return_value=review,
        ),
        patch("app.writing.service.ai_evaluation_available", return_value=True),
    ):
        res = get_pending_status(attempt_id=ATTEMPT, user_id=USER)

    assert res.ai_status == AI_STATUS_COMPLETE
    assert res.ai_band == 6.5
    assert res.ai_available is True
    assert "AI feedback is ready" in res.message


def test_get_review_does_not_call_llm_when_cached():
    attempt = _attempt()
    review = {
        "id": str(REVIEW),
        "status": "pending",
        "human_band": None,
        "reviewer_notes": None,
        "created_at": datetime.now(UTC).isoformat(),
        "ai_scores": {
            "status": AI_STATUS_COMPLETE,
            "ai_band": 6.0,
            "criteria": {
                "task_achievement": 6.0,
                "coherence": 6.0,
                "lexical_resource": 6.0,
                "grammar": 6.0,
            },
            "strengths": ["Clear"],
            "improvements": ["Examples"],
            "model_name": "stub",
            "provider_used": "stub",
        },
    }

    with (
        patch("app.writing.service.repo.get_attempt", return_value=attempt),
        patch(
            "app.writing.service.repo.list_questions_for_part",
            return_value=[_question()],
        ),
        patch(
            "app.writing.service.repo.get_answer_for_attempt",
            return_value={"user_answer": " ".join(["word"] * 200)},
        ),
        patch(
            "app.writing.service.repo.get_mock_test",
            return_value={"title": "Mock 1"},
        ),
        patch(
            "app.writing.service.repo.get_writing_review_for_attempt",
            return_value=review,
        ),
        patch("app.writing.service.repo.get_module_score", return_value=None),
        patch("app.writing.service.ai_evaluation_available", return_value=True),
        patch("app.writing.service.run_writing_evaluation") as run_eval,
        patch("app.writing.service.threading.Thread") as thread_cls,
    ):
        res = get_review(attempt_id=ATTEMPT, user_id=USER)

    run_eval.assert_not_called()
    thread_cls.assert_not_called()
    assert res.ai_status == AI_STATUS_COMPLETE
    assert res.ai_band == 6.0
    assert res.band == 6.0
    assert res.band_source == "ai"
