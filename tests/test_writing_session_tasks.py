"""Writing pending/review session_tasks for dual-task mocks."""

from unittest.mock import patch
from uuid import UUID

from app.writing.service import get_pending_status

USER = UUID("00000000-0000-4000-8000-000000000099")
ATTEMPT_T2 = UUID("00000000-0000-4000-8000-000000000088")
ATTEMPT_T1 = UUID("00000000-0000-4000-8000-000000000087")
MOCK_ATTEMPT = UUID("00000000-0000-4000-8000-000000000066")


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
