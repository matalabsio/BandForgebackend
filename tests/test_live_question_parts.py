"""live_question_parts — catalog config avoids DB on hot path."""

from unittest.mock import patch
from uuid import UUID

from app.mock_catalog.constants import M01_MOCK_TEST_ID
from app.services.mock_orchestrator_repository import live_question_parts

M01 = UUID(M01_MOCK_TEST_ID)
TEST3 = UUID("eb5d9416-da1f-411d-8bf9-07ae4dbc5014")
UNKNOWN = UUID("00000000-0000-4000-8000-000000000099")


def test_m01_listening_uses_legacy_parts_without_db():
    with patch(
        "app.services.mock_orchestrator_repository._question_parts_in_db",
    ) as db_parts:
        parts = live_question_parts(mock_test_id=M01, module="listening")
    db_parts.assert_not_called()
    assert parts == [1, 2, 3, 4]


def test_admin_mock_intersects_configured_with_db_parts():
    with (
        patch(
            "app.mock_catalog.catalog.live_parts_tuple",
            return_value=(1, 2, 3, 4),
        ),
        patch(
            "app.services.mock_orchestrator_repository._question_parts_in_db",
            return_value=[1],
        ),
    ):
        parts = live_question_parts(mock_test_id=TEST3, module="listening")
    assert parts == [1]


def test_admin_mock_returns_empty_when_no_questions():
    with (
        patch(
            "app.mock_catalog.catalog.live_parts_tuple",
            return_value=(1, 2, 3, 4),
        ),
        patch(
            "app.services.mock_orchestrator_repository._question_parts_in_db",
            return_value=[],
        ),
    ):
        parts = live_question_parts(mock_test_id=TEST3, module="listening")
    assert parts == []


def test_unknown_mock_falls_back_to_db():
    with (
        patch(
            "app.mock_catalog.catalog.live_parts_tuple",
            return_value=None,
        ),
        patch(
            "app.services.mock_orchestrator_repository._question_parts_in_db",
            return_value=[1, 2],
        ),
    ):
        parts = live_question_parts(mock_test_id=UNKNOWN, module="listening")
    assert parts == [1, 2]
