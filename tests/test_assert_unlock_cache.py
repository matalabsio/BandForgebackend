"""assert_module_unlocked uses mock_progress unlock snapshot when present."""

from unittest.mock import patch
from uuid import UUID

from app.mock_catalog.constants import M01_MOCK_TEST_ID
from app.schemas.mock_orchestrator import MockUnlockSnapshot
from app.services.mock_orchestrator import assert_module_unlocked

M01 = UUID(M01_MOCK_TEST_ID)
USER = UUID("22222222-2222-4222-8222-222222222222")
MA = UUID("33333333-3333-4333-8333-333333333333")


def test_assert_module_unlocked_uses_unlock_cache():
    snapshot = MockUnlockSnapshot(
        done_parts={"listening": [1]},
        current_module="listening",
        module_status={"listening": "in_progress", "reading": "locked"},
    )
    with (
        patch(
            "app.services.mock_orchestrator._assert_mock_attempt_owner",
            return_value={"id": str(MA)},
        ),
        patch(
            "app.services.mock_orchestrator.read_unlock_snapshot",
            return_value=snapshot,
        ),
        patch(
            "app.services.mock_orchestrator.repo.list_module_attempts",
        ) as list_attempts,
        patch(
            "app.services.mock_orchestrator.repo.list_mock_modules",
        ) as list_modules,
    ):
        assert_module_unlocked(
            mock_attempt_id=MA,
            user_id=USER,
            mock_test_id=M01,
            module="listening",
            part=2,
        )
    list_attempts.assert_not_called()
    list_modules.assert_not_called()
