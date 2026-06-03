"""live_question_parts — catalog config avoids DB on hot path."""

from unittest.mock import patch
from uuid import UUID

from app.mock_catalog.constants import M01_MOCK_TEST_ID
from app.services.mock_orchestrator_repository import live_question_parts

M01 = UUID(M01_MOCK_TEST_ID)
UNKNOWN = UUID("00000000-0000-4000-8000-000000000099")


def test_m01_listening_uses_config_without_db():
    with patch(
        "app.services.mock_orchestrator_repository.distinct_question_parts",
    ) as distinct:
        parts = live_question_parts(mock_test_id=M01, module="listening")
    distinct.assert_not_called()
    assert parts == [1, 2, 3, 4]


def test_unknown_mock_falls_back_to_db():
    with patch(
        "app.services.mock_orchestrator_repository.distinct_question_parts",
        return_value=[1, 2],
    ) as distinct:
        parts = live_question_parts(mock_test_id=UNKNOWN, module="listening")
    distinct.assert_called_once()
    assert parts == [1, 2]
