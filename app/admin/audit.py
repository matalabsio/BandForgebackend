"""Admin audit log helpers."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.db.supabase_client import get_supabase


def log_admin_action(
    *,
    admin_id: UUID,
    action: str,
    resource_type: str,
    resource_id: str | UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    sb = get_supabase()
    sb.table("admin_audit_logs").insert(
        {
            "admin_id": str(admin_id),
            "action": action,
            "resource_type": resource_type,
            "resource_id": str(resource_id) if resource_id is not None else None,
            "metadata": metadata,
        }
    ).execute()
