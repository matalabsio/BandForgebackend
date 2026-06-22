"""Access control for diagnostic guest sessions."""

from uuid import UUID

from fastapi import HTTPException, status

from app.auth.schemas import UserPublic
from app.diagnostic.constants import DIAGNOSTIC_MOCK_TEST_ID


def is_guest_user(user: UserPublic) -> bool:
    return user.role == "guest"


def assert_mock_access(*, user: UserPublic, mock_test_id: UUID) -> None:
    """Guest users may only access the diagnostic mock test."""
    if not is_guest_user(user):
        return
    if mock_test_id != DIAGNOSTIC_MOCK_TEST_ID:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Guest sessions may only access the free diagnostic test.",
        )


def is_diagnostic_mock_test_id(mock_test_id: UUID) -> bool:
    return mock_test_id == DIAGNOSTIC_MOCK_TEST_ID
