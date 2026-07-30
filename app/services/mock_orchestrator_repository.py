"""Data access for mock orchestration (no business rules)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.db.supabase_client import execute_with_retry, get_supabase

logger = logging.getLogger(__name__)

_MIGRATION_HINT = (
    "Apply Supabase migrations: 20260526100000_mock_attempts_orchestration.sql "
    "and 20260526100100_m01_consolidation.sql (SQL Editor or supabase db push)."
)


def _raise_supabase_error(exc: Exception, *, context: str) -> None:
    msg = str(exc)
    if "mock_attempts" in msg or "mock_test_modules" in msg or "PGRST205" in msg:
        detail = f"{context} Database tables may be missing. {_MIGRATION_HINT}"
    elif "does not exist" in msg.lower() or "relation" in msg.lower():
        detail = f"{context} {_MIGRATION_HINT}"
    else:
        detail = f"{context} {msg}"
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=detail,
    ) from exc


def _exec(query):
    return execute_with_retry(query.execute)


def get_mock_test(mock_test_id: UUID, *, allow_unpublished: bool = False) -> dict[str, Any]:
    client = get_supabase()
    try:
        result = (
            client.table("mock_tests")
            .select("id, title, description, is_published")
            .eq("id", str(mock_test_id))
            .limit(1)
        )
        result = _exec(result)
    except Exception as exc:  # noqa: BLE001
        _raise_supabase_error(exc, context="Could not load mock test.")
    rows = result.data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock test not found.")
    row = rows[0]
    if not row.get("is_published") and not allow_unpublished:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock test not found.")
    return row


def list_mock_modules(mock_test_id: UUID) -> list[dict[str, Any]]:
    from app.cache.hybrid_cache import get_json, set_json

    cache_key = f"mock_modules:v2:{mock_test_id}"
    cached = get_json(cache_key)
    if isinstance(cached, list):
        return cached

    client = get_supabase()
    try:
        result = (
            client.table("mock_test_modules")
            .select("module, sequence_order, duration_minutes, is_enabled")
            .eq("mock_test_id", str(mock_test_id))
            .order("sequence_order")
        )
        result = _exec(result)
    except Exception as exc:  # noqa: BLE001
        _raise_supabase_error(exc, context="Could not load mock module config.")
    rows = list(result.data or [])
    set_json(cache_key, rows, ttl_seconds=300)
    return rows


def list_mock_modules_by_ids(
    mock_test_ids: list[UUID],
) -> dict[str, list[dict[str, Any]]]:
    """Batch-load module configs for many mocks (one query for cache misses)."""
    from app.cache.hybrid_cache import get_json, set_json

    out: dict[str, list[dict[str, Any]]] = {}
    missing: list[str] = []
    for mid in mock_test_ids:
        key = str(mid)
        cached = get_json(f"mock_modules:v2:{key}")
        if isinstance(cached, list):
            out[key] = cached
        else:
            missing.append(key)

    if not missing:
        return out

    client = get_supabase()
    try:
        result = _exec(
            client.table("mock_test_modules")
            .select(
                "mock_test_id, module, sequence_order, duration_minutes, is_enabled"
            )
            .in_("mock_test_id", missing)
            .order("sequence_order")
        )
    except Exception as exc:  # noqa: BLE001
        _raise_supabase_error(exc, context="Could not load mock module config.")

    grouped: dict[str, list[dict[str, Any]]] = {mid: [] for mid in missing}
    for row in result.data or []:
        mid = str(row.get("mock_test_id") or "")
        if mid not in grouped:
            grouped[mid] = []
        grouped[mid].append(
            {
                "module": row.get("module"),
                "sequence_order": row.get("sequence_order"),
                "duration_minutes": row.get("duration_minutes"),
                "is_enabled": row.get("is_enabled"),
            }
        )

    for mid, rows in grouped.items():
        set_json(f"mock_modules:v2:{mid}", rows, ttl_seconds=300)
        out[mid] = rows
    return out


def fetch_mock_attempt_progress_bundle(
    *, mock_attempt_id: UUID, user_id: UUID
) -> dict[str, Any] | None:
    """Load mock attempt + modules + attempts + scores in one RPC (fallback: sequential)."""
    client = get_supabase()
    try:
        result = _exec(
            client.rpc(
                "get_mock_attempt_progress",
                {
                    "p_mock_attempt_id": str(mock_attempt_id),
                    "p_user_id": str(user_id),
                },
            )
        )
        data = result.data
        if data is None:
            return None
        if isinstance(data, str):
            import json as _json

            return _json.loads(data)
        if isinstance(data, dict):
            return data
    except Exception as exc:
        logger.warning(
            "get_mock_attempt_progress RPC unavailable, using sequential fallback: %s",
            exc,
        )

    row = (
        client.table("mock_attempts")
        .select("id, user_id, mock_test_id, status, started_at, completed_at, current_module")
        .eq("id", str(mock_attempt_id))
        .limit(1)
    )
    row = _exec(row)
    rows = row.data or []
    if not rows:
        return None
    attempt_row = rows[0]
    if str(attempt_row["user_id"]) != str(user_id):
        return None
    mock_test_id = UUID(str(attempt_row["mock_test_id"]))
    modules = list_mock_modules(mock_test_id)
    module_attempts = list_module_attempts(mock_attempt_id)
    completed_ids = [
        str(a["id"])
        for a in module_attempts
        if a.get("status") == "completed"
    ]
    scores_list: list[dict[str, Any]] = []
    if completed_ids:
        scores = _exec(
            client.table("module_scores")
            .select(
                "attempt_id, module, raw_score, correct_count, total_count, band, "
                "skill_breakdown, scored_at"
            )
            .in_("attempt_id", completed_ids)
        )
        scores_list = list(scores.data or [])
    return {
        "mock_attempt": attempt_row,
        "modules": modules,
        "module_attempts": module_attempts,
        "module_scores": scores_list,
    }


def fetch_mock_start_context(
    *,
    user_id: UUID,
    mock_test_id: UUID,
    allow_unpublished: bool = False,
) -> dict[str, Any] | None:
    """Load mock test + module config + in-progress attempt (one RPC when available)."""
    client = get_supabase()
    try:
        result = _exec(
            client.rpc(
                "get_mock_start_context",
                {
                    "p_user_id": str(user_id),
                    "p_mock_test_id": str(mock_test_id),
                    "p_allow_unpublished": allow_unpublished,
                },
            )
        )
        data = result.data
        if data is None:
            return None
        if isinstance(data, str):
            import json as _json

            data = _json.loads(data)
        if isinstance(data, dict):
            if not data.get("mock_test"):
                return None
            return data
    except Exception as exc:
        logger.warning(
            "get_mock_start_context RPC unavailable, using sequential fallback: %s",
            exc,
        )

    test_row = get_mock_test(mock_test_id, allow_unpublished=allow_unpublished)
    modules = list_mock_modules(mock_test_id)
    in_progress = find_in_progress_mock_attempt(
        user_id=user_id, mock_test_id=mock_test_id
    )
    return {
        "mock_test": test_row,
        "modules": modules,
        "in_progress_attempt": in_progress,
    }


def module_duration_minutes(*, mock_test_id: UUID, module: str) -> int | None:
    """Configured section timer for a mock module, or None if not configured."""
    for row in list_mock_modules(mock_test_id):
        if str(row.get("module")) == module and row.get("is_enabled"):
            return int(row.get("duration_minutes") or 0) or None
    return None


def list_user_mock_attempts(
    *,
    user_id: UUID,
    mock_test_id: UUID,
    limit: int = 50,
) -> list[dict[str, Any]]:
    client = get_supabase()
    try:
        result = (
            client.table("mock_attempts")
            .select(
                "id, mock_test_id, status, started_at, completed_at, current_module"
            )
            .eq("user_id", str(user_id))
            .eq("mock_test_id", str(mock_test_id))
            .order("started_at", desc=True)
            .limit(limit)
        )
        result = _exec(result)
    except Exception as exc:  # noqa: BLE001
        _raise_supabase_error(exc, context="Could not load mock attempt history.")
    return list(result.data or [])


def find_in_progress_mock_attempt(
    *, user_id: UUID, mock_test_id: UUID
) -> dict[str, Any] | None:
    client = get_supabase()
    try:
        result = (
            client.table("mock_attempts")
            .select("id, mock_test_id, status, started_at, completed_at, current_module")
            .eq("user_id", str(user_id))
            .eq("mock_test_id", str(mock_test_id))
            .eq("status", "in_progress")
            .limit(1)
        )
        result = _exec(result)
    except Exception as exc:  # noqa: BLE001
        _raise_supabase_error(exc, context="Could not load in-progress mock attempt.")
    rows = result.data or []
    return rows[0] if rows else None


def insert_mock_attempt(
    *, user_id: UUID, mock_test_id: UUID, current_module: str
) -> dict[str, Any]:
    client = get_supabase()
    try:
        insert = (
            client.table("mock_attempts")
            .insert(
                {
                    "user_id": str(user_id),
                    "mock_test_id": str(mock_test_id),
                    "status": "in_progress",
                    "current_module": current_module,
                }
            )
        )
        insert = _exec(insert)
    except Exception as exc:  # noqa: BLE001
        _raise_supabase_error(exc, context="Could not create mock attempt.")
    if not insert.data:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create mock attempt. {_MIGRATION_HINT}",
        )
    return insert.data[0]


def update_mock_attempt(
    *, mock_attempt_id: UUID, fields: dict[str, Any]
) -> None:
    client = get_supabase()
    _exec(client.table("mock_attempts").update(fields).eq("id", str(mock_attempt_id)))


def list_module_attempts(mock_attempt_id: UUID) -> list[dict[str, Any]]:
    client = get_supabase()
    result = _exec(
        client.table("test_attempts")
        .select("id, module, part, status, started_at, completed_at, mock_attempt_id")
        .eq("mock_attempt_id", str(mock_attempt_id))
    )
    return list(result.data or [])


def list_module_attempts_by_mock_ids(
    mock_attempt_ids: list[UUID],
) -> dict[str, list[dict[str, Any]]]:
    """Batch-load module attempts for history (one query)."""
    if not mock_attempt_ids:
        return {}
    client = get_supabase()
    result = _exec(
        client.table("test_attempts")
        .select("id, module, part, status, started_at, completed_at, mock_attempt_id")
        .in_("mock_attempt_id", [str(mid) for mid in mock_attempt_ids])
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in result.data or []:
        key = str(row.get("mock_attempt_id") or "")
        grouped.setdefault(key, []).append(row)
    return grouped


def distinct_question_parts(*, mock_test_id: UUID, module: str) -> list[int]:
    """Distinct question parts from DB (not cached — stale cache caused 403 on new passages)."""
    client = get_supabase()
    result = _exec(
        client.table("questions")
        .select("part")
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", module)
    )
    parts: set[int] = set()
    for row in result.data or []:
        p = row.get("part")
        if p is not None:
            parts.add(int(p))
    return sorted(parts) if parts else [1]


def _question_parts_in_db(*, mock_test_id: UUID, module: str) -> list[int]:
    """Distinct parts with at least one question row (empty when none)."""
    client = get_supabase()
    result = _exec(
        client.table("questions")
        .select("part")
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", module)
    )
    parts: set[int] = set()
    for row in result.data or []:
        p = row.get("part")
        if p is not None:
            parts.add(int(p))
    return sorted(parts)


def live_question_parts(*, mock_test_id: UUID, module: str) -> list[int]:
    """Parts required to complete a module for orchestrated test progression."""
    from app.mock_catalog.catalog import live_parts_tuple
    from app.mock_catalog.constants import MODULE_LIVE_PARTS

    mock_id_str = str(mock_test_id)

    legacy = MODULE_LIVE_PARTS.get(mock_id_str, {}).get(module)
    if legacy:
        return list(legacy)

    configured = live_parts_tuple(mock_test_id=mock_id_str, module=module)
    db_parts = _question_parts_in_db(mock_test_id=mock_test_id, module=module)

    if configured:
        if not db_parts:
            return []
        db_set = set(db_parts)
        return [p for p in configured if p in db_set]

    return db_parts if db_parts else [1]


def list_module_scores_by_attempt_ids(
    attempt_ids: list[UUID],
) -> dict[str, dict[str, Any]]:
    if not attempt_ids:
        return {}
    client = get_supabase()
    result = _exec(
        client.table("module_scores")
        .select(
            "attempt_id, module, raw_score, correct_count, total_count, band, "
            "skill_breakdown, scored_at"
        )
        .in_("attempt_id", [str(aid) for aid in attempt_ids])
    )
    return {str(row["attempt_id"]): row for row in (result.data or [])}


def list_module_reviews_by_attempt_ids(
    attempt_ids: list[UUID],
) -> dict[str, dict[str, Any]]:
    """Batch-load the latest Writing and Speaking review for each attempt."""
    if not attempt_ids:
        return {}
    client = get_supabase()
    ids = [str(attempt_id) for attempt_id in attempt_ids]
    rows: list[dict[str, Any]] = []
    for table, columns in (
        (
            "writing_reviews",
            "id, attempt_id, status, human_band, ai_scores, created_at",
        ),
        (
            "speaking_reviews",
            "id, attempt_id, status, human_band, ai_scores, evaluation_status, created_at",
        ),
    ):
        result = _exec(
            client.table(table)
            .select(columns)
            .in_("attempt_id", ids)
            .order("created_at", desc=True)
        )
        rows.extend(result.data or [])

    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        attempt_id = str(row.get("attempt_id") or "")
        if attempt_id and attempt_id not in latest:
            latest[attempt_id] = row
    return latest


def get_module_score_band(test_attempt_id: UUID) -> float | None:
    row = get_module_score_row(test_attempt_id)
    if not row or row.get("band") is None:
        return None
    return float(row["band"])


def abandon_in_progress_attempts_for_mock_attempt(*, mock_attempt_id: UUID) -> None:
    """Mark all in-progress module attempts for this mock session as abandoned."""
    client = get_supabase()
    result = _exec(
        client.table("test_attempts")
        .select("id")
        .eq("mock_attempt_id", str(mock_attempt_id))
        .eq("status", "in_progress")
    )
    for row in result.data or []:
        _exec(
            client.table("test_attempts")
            .update({"status": "abandoned"})
            .eq("id", str(row["id"]))
        )


def get_module_score_row(test_attempt_id: UUID) -> dict[str, Any] | None:
    client = get_supabase()
    result = _exec(
        client.table("module_scores")
        .select(
            "attempt_id, module, raw_score, correct_count, total_count, band, scored_at"
        )
        .eq("attempt_id", str(test_attempt_id))
        .limit(1)
    )
    rows = result.data or []
    return rows[0] if rows else None
