"""Admin audit log read API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from app.admin.schemas import (
    AuditLogItem,
    AuditLogResponse,
    ReviewHistoryItem,
    ReviewHistoryResponse,
)
from app.db.supabase_client import get_supabase


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _format_delta(delta: Any) -> str | None:
    if delta is None:
        return None
    try:
        value = float(delta)
    except (TypeError, ValueError):
        return None
    if value == 0:
        return "Δ overall 0"
    sign = "+" if value > 0 else ""
    return f"Δ overall {sign}{value:.1f}"


def _summary_for_action(action: str, metadata: dict[str, Any] | None) -> str:
    meta = metadata or {}
    if action.endswith(".draft"):
        status = meta.get("status")
        if status and status != "unchanged":
            return f"Saved draft · status {status}"
        return "Saved draft"
    if action.endswith(".approve"):
        parts = ["Approved"]
        delta = _format_delta(meta.get("delta_overall"))
        if delta:
            parts.append(delta)
        if meta.get("overridden"):
            parts.append("overridden")
        elif meta.get("ai_band") is not None:
            parts.append("aligned with AI")
        return " · ".join(parts)
    return action


def list_audit_logs(
    *,
    page: int = 1,
    page_size: int = 50,
    resource_type: str | None = None,
    resource_id: UUID | str | None = None,
    action: str | None = None,
) -> AuditLogResponse:
    sb = get_supabase()
    offset = max(0, (page - 1) * page_size)
    query = sb.table("admin_audit_logs").select(
        "id, admin_id, action, resource_type, resource_id, metadata, created_at, users(email)",
        count="exact",
    )
    if resource_type:
        query = query.eq("resource_type", resource_type)
    if resource_id is not None:
        query = query.eq("resource_id", str(resource_id))
    if action:
        query = query.eq("action", action)

    result = (
        query.order("created_at", desc=True)
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


def get_review_history(
    *,
    resource_type: str,
    resource_id: UUID,
    actions: list[str] | None = None,
) -> ReviewHistoryResponse:
    sb = get_supabase()
    query = (
        sb.table("admin_audit_logs")
        .select(
            "id, action, metadata, created_at, users(email)",
        )
        .eq("resource_type", resource_type)
        .eq("resource_id", str(resource_id))
    )
    if actions:
        query = query.in_("action", actions)
    result = query.order("created_at", desc=True).limit(50).execute()
    rows = result.data or []

    items = [
        ReviewHistoryItem(
            id=UUID(str(row["id"])),
            action=str(row["action"]),
            admin_email=(row.get("users") or {}).get("email"),
            summary=_summary_for_action(
                str(row["action"]),
                row.get("metadata") if isinstance(row.get("metadata"), dict) else None,
            ),
            metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else None,
            created_at=_parse_dt(row["created_at"]),
        )
        for row in rows
    ]
    return ReviewHistoryResponse(items=items)
