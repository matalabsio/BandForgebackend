"""DB-backed full-mock catalog helpers."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.db.supabase_client import get_supabase
from app.mock_catalog.constants import MODULE_LIVE_PARTS, PUBLISHED_FULL_MOCK_IDS, is_candidate_live_catalog_number


def is_full_mock_id(mock_id: str) -> bool:
    if mock_id in PUBLISHED_FULL_MOCK_IDS:
        return True
    sb = get_supabase()
    row = (
        sb.table("mock_tests")
        .select("catalog_number")
        .eq("id", mock_id)
        .limit(1)
        .execute()
    ).data
    if not row:
        return False
    cn = row[0].get("catalog_number")
    if cn is None:
        return False
    return is_candidate_live_catalog_number(int(cn))


def live_parts_tuple(*, mock_test_id: str, module: str) -> tuple[int, ...] | None:
    legacy = MODULE_LIVE_PARTS.get(mock_test_id, {}).get(module)
    if legacy:
        return legacy

    sb = get_supabase()
    row = (
        sb.table("mock_tests")
        .select("listening_parts, reading_passages, writing_tasks")
        .eq("id", mock_test_id)
        .limit(1)
        .execute()
    ).data
    if not row:
        return None

    counts = row[0]
    key_map = {
        "listening": "listening_parts",
        "reading": "reading_passages",
        "writing": "writing_tasks",
    }
    field = key_map.get(module)
    if not field:
        return None
    count = int(counts.get(field) or 0)
    if count <= 0:
        return None
    return tuple(range(1, count + 1))


def list_catalog_mock_rows(*, include_unpublished: bool = False) -> list[dict[str, Any]]:
    sb = get_supabase()
    query = (
        sb.table("mock_tests")
        .select(
            "id, title, description, is_published, status, catalog_number, "
            "listening_parts, reading_passages, writing_tasks, created_at, "
            "is_diagnostic"
        )
        .not_.is_("catalog_number", "null")
        .eq("is_diagnostic", False)
        .order("catalog_number")
    )
    if not include_unpublished:
        query = query.eq("is_published", True).eq("status", "published")
    rows = list((query.execute()).data or [])
    return [
        row
        for row in rows
        if is_candidate_live_catalog_number(
            int(row["catalog_number"])
            if row.get("catalog_number") is not None
            else None
        )
        and not bool(row.get("is_diagnostic"))
        and str(row.get("status") or "") != "archived"
    ]


def next_catalog_number() -> int:
    sb = get_supabase()
    rows = (
        sb.table("mock_tests")
        .select("catalog_number")
        .not_.is_("catalog_number", "null")
        .order("catalog_number", desc=True)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        return 1
    return int(rows[0]["catalog_number"]) + 1
