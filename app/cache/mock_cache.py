"""Mock-related cache invalidation and progress/unlock snapshot cache."""

from __future__ import annotations

import logging
from threading import Thread
from time import perf_counter
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.cache.hybrid_cache import delete_many, get_json, invalidate_prefix, set_json

if TYPE_CHECKING:
    from app.services.mock_progress_timing import MockProgressTiming

logger = logging.getLogger(__name__)


def _elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)
from app.schemas.mock_orchestrator import (
    InProgressMockAttempt,
    MockAttemptProgress,
    MockProgressCachePayload,
    MockUnlockSnapshot,
)

PROGRESS_CACHE_TTL_SECONDS = 30


def progress_cache_key(*, mock_attempt_id: UUID, user_id: UUID) -> str:
    # v2: free-module-access statuses (busts pre-unlock locked snapshots)
    return f"mock_progress:v2:{mock_attempt_id}:{user_id}"


def refresh_mock_in_progress_cache(
    *,
    user_id: UUID,
    mock_test_id: UUID,
    mock_attempt_id: UUID,
    status: str,
    current_module: str | None,
) -> None:
    """Update mock_in_progress without deleting progress/session keys (SET not DELETE)."""
    key = f"mock_in_progress:{user_id}:{mock_test_id}"
    if status != "in_progress":
        delete_many([key])
        return
    payload = InProgressMockAttempt(
        mock_attempt_id=mock_attempt_id,
        mock_test_id=mock_test_id,
        status=status,
        current_module=current_module,  # type: ignore[arg-type]
    ).model_dump(mode="json")
    set_json(key, payload, ttl_seconds=10)


def write_progress_cache(
    *,
    mock_attempt_id: UUID,
    user_id: UUID,
    mock_test_id: UUID,
    progress: MockAttemptProgress,
    unlock: MockUnlockSnapshot,
    timing: MockProgressTiming | None = None,
) -> None:
    """Write combined progress+unlock payload and session progress snapshot."""
    key = progress_cache_key(mock_attempt_id=mock_attempt_id, user_id=user_id)
    session_key = f"mock_session:v2:{user_id}:{mock_test_id}"

    t0 = perf_counter()
    payload = MockProgressCachePayload(progress=progress, unlock=unlock)
    progress_unlock_blob = payload.model_dump(mode="json")
    session_blob = progress.model_dump(mode="json")
    if timing is not None:
        timing.serialize_progress_ms = _elapsed_ms(t0)

    t0 = perf_counter()
    set_json(key, progress_unlock_blob, ttl_seconds=PROGRESS_CACHE_TTL_SECONDS)
    if timing is not None:
        # Unlock is embedded in this key (no separate Redis write in this path).
        timing.set_progress_cache_ms = _elapsed_ms(t0)
        timing.set_unlock_cache_ms = 0

    t0 = perf_counter()
    set_json(session_key, session_blob, ttl_seconds=PROGRESS_CACHE_TTL_SECONDS)
    if timing is not None:
        timing.set_session_cache_ms = _elapsed_ms(t0)


async def write_progress_cache_async(
    *,
    mock_attempt_id: UUID,
    user_id: UUID,
    mock_test_id: UUID,
    progress: MockAttemptProgress,
    unlock: MockUnlockSnapshot,
    timing: MockProgressTiming | None = None,
) -> None:
    """Like write_progress_cache but writes the two cache keys concurrently."""
    import asyncio

    key = progress_cache_key(mock_attempt_id=mock_attempt_id, user_id=user_id)
    session_key = f"mock_session:v2:{user_id}:{mock_test_id}"

    t0 = perf_counter()
    payload = MockProgressCachePayload(progress=progress, unlock=unlock)
    progress_unlock_blob = payload.model_dump(mode="json")
    session_blob = progress.model_dump(mode="json")
    if timing is not None:
        timing.serialize_progress_ms = _elapsed_ms(t0)

    t0 = perf_counter()
    await asyncio.gather(
        asyncio.to_thread(
            set_json,
            key,
            progress_unlock_blob,
            PROGRESS_CACHE_TTL_SECONDS,
        ),
        asyncio.to_thread(
            set_json,
            session_key,
            session_blob,
            PROGRESS_CACHE_TTL_SECONDS,
        ),
    )
    wall = _elapsed_ms(t0)
    if timing is not None:
        timing.set_progress_cache_ms = wall
        timing.set_unlock_cache_ms = 0
        timing.set_session_cache_ms = wall


def write_unlock_snapshot_cache(
    *,
    mock_attempt_id: UUID,
    user_id: UUID,
    unlock: MockUnlockSnapshot,
    timing: MockProgressTiming | None = None,
) -> None:
    """Update unlock slice without requiring a full MockAttemptProgress build."""
    key = progress_cache_key(mock_attempt_id=mock_attempt_id, user_id=user_id)
    t0 = perf_counter()
    existing = get_json(key)
    payload: dict[str, Any] = (
        dict(existing) if isinstance(existing, dict) else {}
    )
    payload["unlock"] = unlock.model_dump(mode="json")
    if timing is not None:
        timing.serialize_progress_ms = _elapsed_ms(t0)
    t0 = perf_counter()
    set_json(key, payload, ttl_seconds=PROGRESS_CACHE_TTL_SECONDS)
    if timing is not None:
        timing.set_unlock_cache_ms = _elapsed_ms(t0)


def read_unlock_snapshot(
    *, mock_attempt_id: UUID, user_id: UUID
) -> MockUnlockSnapshot | None:
    cached = get_json(progress_cache_key(mock_attempt_id=mock_attempt_id, user_id=user_id))
    if not isinstance(cached, dict):
        return None
    unlock_raw = cached.get("unlock")
    if not isinstance(unlock_raw, dict):
        return None
    try:
        return MockUnlockSnapshot.model_validate(unlock_raw)
    except Exception:
        return None


def read_progress_from_cache(
    *, mock_attempt_id: UUID, user_id: UUID
) -> MockAttemptProgress | None:
    cached = get_json(progress_cache_key(mock_attempt_id=mock_attempt_id, user_id=user_id))
    if not isinstance(cached, dict):
        return None
    progress_raw: Any = cached.get("progress", cached)
    if not isinstance(progress_raw, dict):
        return None
    try:
        return MockAttemptProgress.model_validate(progress_raw)
    except Exception:
        return None


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
            f"mock_session:v2:{user_id}:{mock_test_id}",
        ]
    )


def invalidate_mock_history_caches(*, user_id: UUID, mock_test_id: UUID) -> None:
    """Drop cached mock history lists (Redis SCAN). Not on submit hot path."""
    invalidate_prefix(f"mock_history:{user_id}:{mock_test_id}")
    invalidate_prefix(f"mock_history_lite:{user_id}:{mock_test_id}")


def schedule_mock_history_cache_invalidation(
    *, user_id: UUID, mock_test_id: UUID
) -> None:
    """Fire-and-forget history cache refresh after mock completion."""
    def _run() -> None:
        try:
            invalidate_mock_history_caches(user_id=user_id, mock_test_id=mock_test_id)
        except Exception:
            logger.exception(
                "Background mock history cache invalidation failed "
                "(user_id=%s mock_test_id=%s)",
                user_id,
                mock_test_id,
            )

    Thread(
        target=_run,
        name=f"mock-history-invalidate-{user_id}-{mock_test_id}",
        daemon=True,
    ).start()
