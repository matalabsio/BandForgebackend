"""Admin audit log read API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from app.admin.schemas import AuditLogItem, AuditLogResponse
from app.db.supabase_client import get_supabase


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def list_audit_logs(*, page: int = 1, page_size: int = 50) -> AuditLogResponse:
    sb = get_supabase()
    offset = max(0, (page - 1) * page_size)
    result = (
        sb.table("admin_audit_logs")
        .select(
            "id, admin_id, action, resource_type, resource_id, metadata, created_at, users(email)",
            count="exact",
        )
        .order("created_at", desc=True)
        .range(offset, offset + page_size - 1)
        .execute()
    )
    rows = result.data or []
    total = result.count or len(rows)

    items = [
        AuditLogItem(
            id=UUID(str(row["id"])),
            admin_id=UUID(str(row["admin_id"])),
            admin_email=(row.get("users") or {}).get("email"),
            action=str(row["action"]),
            resource_type=str(row["resource_type"]),
            resource_id=row.get("resource_id"),
            metadata=row.get("metadata"),
            created_at=_parse_dt(row["created_at"]),
        )
        for row in rows
    ]

    return AuditLogResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )
