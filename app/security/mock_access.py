"""Lookup helpers for mock free/paid entitlements."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.db.supabase_client import execute_with_retry, get_supabase


def get_mock_access_flags(mock_test_id: UUID) -> dict[str, Any] | None:
    """Return ``{is_free, is_diagnostic}`` for a mock, or None if missing."""
    sb = get_supabase()
    result = execute_with_retry(
        sb.table("mock_tests")
        .select("id, is_free, is_diagnostic")
        .eq("id", str(mock_test_id))
        .limit(1)
        .execute
    )
    if not result.data:
        return None
    row = result.data[0]
    return {
        "is_free": bool(row.get("is_free")),
        "is_diagnostic": bool(row.get("is_diagnostic")),
    }
