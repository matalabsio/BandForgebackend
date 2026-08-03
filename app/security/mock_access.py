"""Lookup helpers for mock free/paid entitlements."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.db.supabase_client import execute_with_retry, get_supabase


def get_mock_access_flags(mock_test_id: UUID) -> dict[str, Any] | None:
    """Return ``{is_free, is_diagnostic}`` for a mock, or None if missing."""
    from app.cache.hybrid_cache import get_json, set_json

    cache_key = f"mock:access:{mock_test_id}"
    cached = get_json(cache_key)
    if isinstance(cached, dict):
        if cached.get("__miss__"):
            return None
        return cached

    sb = get_supabase()
    result = execute_with_retry(
        sb.table("mock_tests")
        .select("id, is_free, is_diagnostic")
        .eq("id", str(mock_test_id))
        .limit(1)
        .execute
    )
    if not result.data:
        set_json(cache_key, {"__miss__": True}, 300)
        return None
    row = result.data[0]
    flags = {
        "is_free": bool(row.get("is_free")),
        "is_diagnostic": bool(row.get("is_diagnostic")),
    }
    set_json(cache_key, flags, 300)
    return flags
