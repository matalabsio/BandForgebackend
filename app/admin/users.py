"""Admin user management."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.admin.audit import log_admin_action
from app.admin.schemas import (
    AdminUserAttemptItem,
    AdminUserActivityStats,
    AdminUserDetail,
    AdminUserDiagnosticItem,
    AdminUserInProgressItem,
    AdminUserListItem,
    AdminUserListResponse,
    AdminUserMockSessionItem,
    AdminUserModuleAttemptItem,
    AdminUserOverview,
    AdminUserSpeakingReviewItem,
    PatchAdminUserRequest,
)
from app.db.supabase_client import get_supabase
from app.services import user_activity


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _admin_role(raw: str | None) -> str:
    """Map DB role to an admin-safe label (guest accounts are diagnostic-only)."""
    role = raw or "student"
    if role in ("student", "admin", "super_admin", "guest"):
        return role
    return "student"


def list_users(
    *,
    q: str | None = None,
    role: str | None = None,
    active: bool | None = None,
    page: int = 1,
    page_size: int = 25,
) -> AdminUserListResponse:
    sb = get_supabase()
    query = sb.table("users").select(
        "id, email, full_name, role, is_active, created_at",
        count="exact",
    )
    if q:
        pattern = f"%{q.strip()}%"
        query = query.or_(f"email.ilike.{pattern},full_name.ilike.{pattern}")
    if role:
        query = query.eq("role", role)
    else:
        # Diagnostic guest JWT accounts are not real students — hide from default list.
        query = query.neq("role", "guest")
    if active is not None:
        query = query.eq("is_active", active)

    offset = max(0, (page - 1) * page_size)
    result = (
        query.order("created_at", desc=True)
        .range(offset, offset + page_size - 1)
        .execute()
    )
    rows = result.data or []
    total = result.count or len(rows)

    user_ids = [str(row["id"]) for row in rows]
    aggregates = user_activity.batch_user_list_aggregates(user_ids)

    items: list[AdminUserListItem] = []
    for row in rows:
        uid = str(row["id"])
        agg = aggregates.get(uid, {})
        items.append(
            AdminUserListItem(
                id=UUID(uid),
                email=row.get("email"),
                full_name=row.get("full_name"),
                role=_admin_role(row.get("role")),
                is_active=bool(row.get("is_active", True)),
                created_at=_parse_dt(row["created_at"]),
                mock_attempt_count=int(agg.get("mock_attempt_count") or 0),
                completed_mock_count=int(agg.get("completed_mock_count") or 0),
                last_activity_at=agg.get("last_activity_at"),
                best_band=agg.get("best_band"),
            )
        )

    return AdminUserListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


def get_user_detail(user_id: UUID) -> AdminUserDetail:
    sb = get_supabase()
    result = (
        sb.table("users")
        .select(
            "id, email, full_name, phone, role, is_active, email_verified_at, "
            "created_at, target_band"
        )
        .eq("id", str(user_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    row = result.data[0]
    uid = str(row["id"])

    mock_count = (
        sb.table("mock_attempts")
        .select("id", count="exact")
        .eq("user_id", uid)
        .execute()
    ).count or 0

    completed = (
        sb.table("mock_attempts")
        .select("id", count="exact")
        .eq("user_id", uid)
        .eq("status", "completed")
        .execute()
    ).count or 0

    return AdminUserDetail(
        id=UUID(uid),
        email=row.get("email"),
        full_name=row.get("full_name"),
        phone=row.get("phone"),
        role=_admin_role(row.get("role")),
        is_active=bool(row.get("is_active", True)),
        email_verified=row.get("email_verified_at") is not None,
        created_at=_parse_dt(row["created_at"]),
        mock_attempt_count=mock_count,
        completed_mock_count=completed,
        target_band=(
            float(row["target_band"]) if row.get("target_band") is not None else None
        ),
    )


def list_user_attempts(user_id: UUID) -> list[AdminUserAttemptItem]:
    sb = get_supabase()
    uid = str(user_id)

    mock_rows = (
        sb.table("mock_attempts")
        .select("id, mock_test_id, status, started_at, completed_at, mock_tests(title)")
        .eq("user_id", uid)
        .order("started_at", desc=True)
        .limit(50)
        .execute()
    ).data or []

    items: list[AdminUserAttemptItem] = []
    for row in mock_rows:
        mock_ref = row.get("mock_tests") or {}
        items.append(
            AdminUserAttemptItem(
                id=UUID(str(row["id"])),
                kind="mock",
                mock_test_id=UUID(str(row["mock_test_id"])),
                mock_title=mock_ref.get("title"),
                status=str(row["status"]),
                started_at=_parse_dt(row["started_at"]),
                completed_at=(
                    _parse_dt(row["completed_at"]) if row.get("completed_at") else None
                ),
            )
        )

    module_rows = (
        sb.table("test_attempts")
        .select(
            "id, mock_test_id, module, status, started_at, completed_at, mock_tests(title)"
        )
        .eq("user_id", uid)
        .order("started_at", desc=True)
        .limit(50)
        .execute()
    ).data or []

    for row in module_rows:
        mock_ref = row.get("mock_tests") or {}
        band: float | None = None
        if row.get("status") == "completed":
            scores = (
                sb.table("module_scores")
                .select("band")
                .eq("attempt_id", str(row["id"]))
                .limit(1)
                .execute()
            ).data or []
            if scores and scores[0].get("band") is not None:
                band = float(scores[0]["band"])

        items.append(
            AdminUserAttemptItem(
                id=UUID(str(row["id"])),
                kind="module",
                mock_test_id=(
                    UUID(str(row["mock_test_id"])) if row.get("mock_test_id") else None
                ),
                mock_title=mock_ref.get("title"),
                module=str(row.get("module")),
                status=str(row["status"]),
                started_at=_parse_dt(row["started_at"]),
                completed_at=(
                    _parse_dt(row["completed_at"]) if row.get("completed_at") else None
                ),
                band=band,
            )
        )

    items.sort(key=lambda x: x.started_at, reverse=True)
    return items[:50]


def patch_user(
    *,
    user_id: UUID,
    body: PatchAdminUserRequest,
    admin_id: UUID,
    is_super_admin: bool,
) -> AdminUserDetail:
    if body.role is not None and not is_super_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Only super admins can change roles.",
        )

    if body.role is not None and body.role in {"admin", "super_admin"}:
        from app.admin.dependencies import is_admin_email_allowed

        sb = get_supabase()
        target = (
            sb.table("users")
            .select("email")
            .eq("id", str(user_id))
            .limit(1)
            .execute()
        ).data
        if not target:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
        target_email = str(target[0].get("email") or "")
        if not is_admin_email_allowed(target_email):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="Only the configured admin email can hold an admin role.",
            )

    updates: dict[str, Any] = {}
    if body.is_active is not None:
        updates["is_active"] = body.is_active
    if body.role is not None:
        updates["role"] = body.role

    if not updates:
        return get_user_detail(user_id)

    sb = get_supabase()
    sb.table("users").update(updates).eq("id", str(user_id)).execute()

    action = "user.deactivate" if body.is_active is False else "user.update"
    log_admin_action(
        admin_id=admin_id,
        action=action,
        resource_type="user",
        resource_id=user_id,
        metadata=updates,
    )

    return get_user_detail(user_id)


def get_user_overview(user_id: UUID) -> AdminUserOverview:
    from app.admin.parallel import run_parallel
    from app.perf.timing import timed_call

    profile = timed_call("user_overview.profile", lambda: get_user_detail(user_id))

    loaded = timed_call(
        "user_overview.sections_parallel",
        lambda: run_parallel(
            {
                "activity": lambda: user_activity.build_user_activity_stats(user_id),
                "mock_sessions": lambda: user_activity.build_user_mock_sessions(user_id),
                "diagnostics": lambda: user_activity.list_user_diagnostics(user_id),
                "speaking_reviews": lambda: user_activity.list_user_speaking_reviews(
                    user_id
                ),
            }
        ),
    )

    activity = loaded["activity"]
    stats = AdminUserActivityStats(
        total_attempts=activity["total_attempts"],
        completed_attempts=activity["completed_attempts"],
        in_progress_attempts=activity["in_progress_attempts"],
        average_band=activity["average_band"],
        best_band=activity["best_band"],
        last_activity_at=activity["last_activity_at"],
        current_streak=activity["current_streak"],
        longest_streak=activity["longest_streak"],
    )

    in_progress = [
        AdminUserInProgressItem.model_validate(row)
        for row in activity["in_progress"]
    ]
    recent_modules = [
        AdminUserModuleAttemptItem.model_validate(row)
        for row in activity["recent_modules"]
    ]
    mock_sessions = [
        AdminUserMockSessionItem.model_validate(row)
        for row in loaded["mock_sessions"]
    ]
    diagnostics = [
        AdminUserDiagnosticItem.model_validate(row) for row in loaded["diagnostics"]
    ]
    speaking_reviews = [
        AdminUserSpeakingReviewItem.model_validate(row)
        for row in loaded["speaking_reviews"]
    ]

    return AdminUserOverview(
        profile=profile,
        stats=stats,
        in_progress=in_progress,
        recent_modules=recent_modules,
        mock_sessions=mock_sessions,
        diagnostics=diagnostics,
        speaking_reviews=speaking_reviews,
    )
