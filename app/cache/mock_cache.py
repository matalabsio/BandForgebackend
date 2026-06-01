"""Mock-related cache invalidation (Phase 2 — narrow keys, keep catalog caches)."""

from __future__ import annotations

from uuid import UUID

from app.cache.hybrid_cache import delete_many, invalidate_prefix


def invalidate_mock_progress_caches(
    *,
    user_id: UUID,
    mock_test_id: UUID,
    mock_attempt_id: UUID,
) -> None:
    """Drop user progress/session caches without touching static question catalogs."""
    delete_many(
        [
            f"mock_progress:{mock_attempt_id}:{user_id}",
            f"mock_in_progress:{user_id}:{mock_test_id}",
            f"mock_session:{user_id}:{mock_test_id}",
        ]
    )


def invalidate_mock_history_caches(*, user_id: UUID, mock_test_id: UUID) -> None:
    invalidate_prefix(f"mock_history:{user_id}:{mock_test_id}")
    invalidate_prefix(f"mock_history_lite:{user_id}:{mock_test_id}")
