"""Reading start scopes in-progress attempts to the active mock session."""

from unittest.mock import MagicMock, patch
from uuid import UUID

from app.reading.service import start_attempt
from app.schemas.test_engine import TestSummary

M01 = UUID("a0000000-0000-4000-8000-000000000001")
USER = UUID("22222222-2222-4222-8222-222222222222")
MOCK_A = UUID("33333333-3333-4333-8333-333333333333")
ORPHAN_ID = UUID("44444444-4444-4444-8444-444444444444")
NEW_ID = UUID("55555555-5555-4555-8555-555555555555")


def test_start_reading_abandons_orphan_without_matching_mock_attempt():
    orphan = {
        "id": str(ORPHAN_ID),
        "started_at": "2026-01-01T00:00:00+00:00",
        "status": "in_progress",
        "mock_attempt_id": None,
    }
    new_row = {
        "id": str(NEW_ID),
        "started_at": "2026-01-02T00:00:00+00:00",
        "status": "in_progress",
        "mock_attempt_id": str(MOCK_A),
    }

    with (
        patch("app.reading.service.repo.get_mock_test", return_value={"id": str(M01)}),
        patch("app.services.mock_orchestrator.assert_module_unlocked"),
        patch("app.reading.service.repo.abandon_stale_reading_attempts") as stale_mock,
        patch(
            "app.reading.service.repo.find_in_progress_reading_attempt",
            return_value=orphan,
        ) as find_mock,
        patch(
            "app.reading.service.repo.abandon_reading_attempt",
        ) as abandon_mock,
        patch(
            "app.reading.service.repo.insert_reading_attempt",
            return_value=new_row,
        ) as insert_mock,
        patch(
            "app.reading.service._pack_session_content",
            return_value=(TestSummary(id=M01, title="Mock"), "", []),
        ),
        patch(
            "app.reading.service._reading_duration_seconds",
            return_value=1200,
        ),
        patch(
            "app.reading.service._mock_reading_session_started_at",
            return_value=__import__("datetime").datetime(
                2026, 1, 2, tzinfo=__import__("datetime").UTC
            ),
        ),
    ):
        res = start_attempt(
            mock_test_id=M01,
            user_id=USER,
            part=1,
            mock_attempt_id=MOCK_A,
            include_questions=False,
        )

    find_mock.assert_called_once()
    assert find_mock.call_args.kwargs["mock_attempt_id"] == MOCK_A
    abandon_mock.assert_called_once_with(attempt_id=ORPHAN_ID)
    insert_mock.assert_called_once()
    assert res.attempt_id == NEW_ID


def test_start_reading_abandons_stale_rows_not_visible_to_scoped_find():
    """Stale cleanup runs in background after start (router), not on the hot path."""
    new_row = {
        "id": str(NEW_ID),
        "started_at": "2026-01-02T00:00:00+00:00",
        "status": "in_progress",
        "mock_attempt_id": str(MOCK_A),
    }

    with (
        patch("app.reading.service.repo.get_mock_test", return_value={"id": str(M01)}),
        patch("app.services.mock_orchestrator.assert_module_unlocked"),
        patch(
            "app.reading.service.repo.abandon_stale_reading_attempts",
        ) as stale_mock,
        patch(
            "app.reading.service.repo.find_in_progress_reading_attempt",
            return_value=None,
        ),
        patch(
            "app.reading.service.repo.insert_reading_attempt",
            return_value=new_row,
        ),
        patch(
            "app.reading.service._pack_session_content",
            return_value=(TestSummary(id=M01, title="Mock"), "", []),
        ),
        patch(
            "app.reading.service._reading_duration_seconds",
            return_value=1200,
        ),
        patch(
            "app.reading.service._mock_reading_session_started_at",
            return_value=__import__("datetime").datetime(
                2026, 1, 2, tzinfo=__import__("datetime").UTC
            ),
        ),
    ):
        start_attempt(
            mock_test_id=M01,
            user_id=USER,
            part=1,
            mock_attempt_id=MOCK_A,
            include_questions=False,
        )

    stale_mock.assert_not_called()
