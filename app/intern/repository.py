"""Supabase access for intern_applications."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.db.supabase_client import get_supabase

TABLE = "intern_applications"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def insert_application(payload: dict[str, Any]) -> dict[str, Any]:
    sb = get_supabase()
    result = sb.table(TABLE).insert(payload).execute()
    if not result.data:
        raise RuntimeError("Could not create intern application.")
    return result.data[0]


def get_by_token(token: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table(TABLE)
        .select("*")
        .eq("access_token", token.strip())
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_by_id(application_id: UUID) -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table(TABLE)
        .select("*")
        .eq("id", str(application_id))
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def update_application(application_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    sb = get_supabase()
    body = {**payload, "updated_at": _now()}
    result = sb.table(TABLE).update(body).eq("id", application_id).execute()
    if not result.data:
        raise RuntimeError("Could not update intern application.")
    return result.data[0]


def list_applications(*, page: int, page_size: int, q: str | None = None) -> tuple[list[dict[str, Any]], int]:
    sb = get_supabase()
    query = sb.table(TABLE).select("*", count="exact").order("created_at", desc=True)
    if q and q.strip():
        term = q.strip()
        query = query.or_(f"full_name.ilike.%{term}%,email.ilike.%{term}%,college.ilike.%{term}%")
    start = (page - 1) * page_size
    end = start + page_size - 1
    result = query.range(start, end).execute()
    return list(result.data or []), int(result.count or 0)
