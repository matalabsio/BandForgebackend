"""Supabase accessors for practice hubs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.db.supabase_client import execute_with_retry, get_supabase

SKILLS = ("listening", "reading", "writing", "speaking")

HUB_LIST_COLUMNS = (
    "id, slug, estimated_min, sort_order, practice_prompt, "
    "practice_sets!inner(set_number, practice_banks!inner(skill, bank_number, title))"
)

HUB_DETAIL_COLUMNS = (
    "id, slug, videos, practice_prompt, submit_config, estimated_min, sort_order, "
    "practice_sets!inner(set_number, title, practice_banks!inner(skill, bank_number, title))"
)


def _exec(query):
    return execute_with_retry(query.execute)


def list_hubs_for_skill(skill: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("practice_hubs")
        .select(HUB_LIST_COLUMNS)
        .eq("practice_sets.practice_banks.skill", skill)
        .order("sort_order")
        .execute()
    )
    return list(result.data or [])


def list_all_hubs_grouped() -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {s: [] for s in SKILLS}
    for skill in SKILLS:
        grouped[skill] = list_hubs_for_skill(skill)
    return grouped


def get_hub_by_id(hub_id: str | UUID) -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table("practice_hubs")
        .select(HUB_DETAIL_COLUMNS)
        .eq("id", str(hub_id))
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def get_user_progress_map(user_id: UUID) -> dict[str, dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("user_hub_progress")
        .select("hub_id, status, completed_at")
        .eq("user_id", str(user_id))
        .execute()
    )
    return {str(row["hub_id"]): row for row in (result.data or [])}


def upsert_hub_completed(*, user_id: UUID, hub_id: str | UUID) -> dict[str, Any]:
    sb = get_supabase()
    now = datetime.now(UTC).isoformat()
    payload = {
        "user_id": str(user_id),
        "hub_id": str(hub_id),
        "status": "completed",
        "completed_at": now,
        "updated_at": now,
    }
    result = _exec(
        sb.table("user_hub_progress").upsert(
            payload,
            on_conflict="user_id,hub_id",
        )
    )
    rows = result.data or []
    if rows:
        return rows[0]
    read = (
        sb.table("user_hub_progress")
        .select("*")
        .eq("user_id", str(user_id))
        .eq("hub_id", str(hub_id))
        .limit(1)
        .execute()
    )
    return (read.data or [{}])[0]


def count_completed_for_skill(*, user_id: UUID, skill: str) -> int:
    hubs = list_hubs_for_skill(skill)
    if not hubs:
        return 0
    hub_ids = [str(h["id"]) for h in hubs]
    progress = get_user_progress_map(user_id)
    return sum(
        1
        for hid in hub_ids
        if progress.get(hid, {}).get("status") == "completed"
    )


def get_skill_full_mock(skill: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table("skill_full_mocks")
        .select("skill, mock_test_id, unlock_requires_sets")
        .eq("skill", skill)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def list_skill_full_mocks() -> list[dict[str, Any]]:
    sb = get_supabase()
    result = sb.table("skill_full_mocks").select("*").execute()
    return list(result.data or [])


def _flatten_hub_row(row: dict[str, Any]) -> dict[str, Any]:
    sets = row.get("practice_sets") or {}
    if isinstance(sets, list):
        sets = sets[0] if sets else {}
    banks = sets.get("practice_banks") or {}
    if isinstance(banks, list):
        banks = banks[0] if banks else {}
    return {
        "id": str(row["id"]),
        "slug": row.get("slug") or "",
        "skill": banks.get("skill") or "",
        "bank_number": int(banks.get("bank_number") or 0),
        "set_number": int(sets.get("set_number") or 0),
        "title": sets.get("title") or row.get("slug") or "",
        "estimated_min": int(row.get("estimated_min") or 25),
        "sort_order": int(row.get("sort_order") or 0),
        "videos": row.get("videos") or [],
        "practice_prompt": row.get("practice_prompt") or "",
        "submit_config": row.get("submit_config") or {},
    }
