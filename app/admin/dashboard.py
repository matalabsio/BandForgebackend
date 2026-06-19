"""Admin dashboard metrics and activity feed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.admin.schemas import (
    DailyActivityPoint,
    DashboardMetrics,
    DashboardOverview,
    RecentActivityItem,
)
from app.db.supabase_client import get_supabase


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _trend_pct(current: int, previous: int) -> int | None:
    if previous <= 0:
        return 100 if current > 0 else None
    return round(((current - previous) / previous) * 100)


def _day_buckets(*, days: int = 7) -> list[dict[str, Any]]:
    now = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    buckets: list[dict[str, Any]] = []
    for offset in range(days - 1, -1, -1):
        start = now - timedelta(days=offset)
        end = start + timedelta(days=1)
        buckets.append(
            {
                "label": start.strftime("%a"),
                "date": start.date().isoformat(),
                "start": start,
                "end": end,
                "active_users": set(),
                "signups": 0,
                "mock_attempts": 0,
            }
        )
    return buckets


def _bucket_index(buckets: list[dict[str, Any]], ts: datetime) -> int | None:
    for i, bucket in enumerate(buckets):
        if bucket["start"] <= ts < bucket["end"]:
            return i
    return None


def _format_audit_message(action: str, metadata: dict[str, Any] | None) -> str:
    meta = metadata or {}
    if action == "mock.published":
        return "Admin published a mock test"
    if action == "mock.ingest_publish":
        mod = meta.get("module", "content")
        part = meta.get("part")
        suffix = f" (part {part})" if part else ""
        return f"Admin uploaded {mod} questions{suffix}"
    if action == "mock.create":
        title = meta.get("title")
        return f"Admin created mock{f' "{title}"' if title else ''}"
    if action == "question.edit":
        return "Admin edited a question"
    if action == "mock.audio_upload":
        return "Admin uploaded listening audio"
    return f"Admin action: {action.replace('.', ' ')}"


def get_dashboard_overview() -> DashboardOverview:
    sb = get_supabase()
    now = datetime.now(UTC)
    since_7d = (now - timedelta(days=7)).isoformat()
    since_14d = (now - timedelta(days=14)).isoformat()

    users = sb.table("users").select("id", count="exact").execute()
    total_users = users.count or 0

    signups_7d = (
        sb.table("users")
        .select("id", count="exact")
        .gte("created_at", since_7d)
        .execute()
    ).count or 0

    signups_prev_7d = (
        sb.table("users")
        .select("id", count="exact")
        .gte("created_at", since_14d)
        .lt("created_at", since_7d)
        .execute()
    ).count or 0

    mock_attempts_7d = (
        sb.table("mock_attempts")
        .select("id", count="exact")
        .gte("started_at", since_7d)
        .execute()
    ).count or 0

    mock_attempts_prev_7d = (
        sb.table("mock_attempts")
        .select("id", count="exact")
        .gte("started_at", since_14d)
        .lt("started_at", since_7d)
        .execute()
    ).count or 0

    speaking_pending = (
        sb.table("speaking_reviews")
        .select("id", count="exact")
        .eq("status", "pending")
        .execute()
    ).count or 0

    mock_rows = (
        sb.table("mock_tests")
        .select("id, status, catalog_number")
        .not_.is_("catalog_number", "null")
        .execute()
    ).data or []
    total_mocks = len(mock_rows)
    published_mocks = sum(1 for r in mock_rows if r.get("status") == "published")

    active_user_ids: set[str] = set()
    prev_active_user_ids: set[str] = set()
    buckets = _day_buckets()

    attempt_rows = (
        sb.table("mock_attempts")
        .select("user_id, started_at")
        .gte("started_at", since_14d)
        .execute()
    ).data or []
    for row in attempt_rows:
        uid = row.get("user_id")
        started = row.get("started_at")
        if not uid or not started:
            continue
        ts = _parse_dt(started)
        uid_str = str(uid)
        if ts >= _parse_dt(since_7d):
            active_user_ids.add(uid_str)
            idx = _bucket_index(buckets, ts)
            if idx is not None:
                buckets[idx]["mock_attempts"] += 1
                buckets[idx]["active_users"].add(uid_str)
        elif ts >= _parse_dt(since_14d):
            prev_active_user_ids.add(uid_str)

    test_attempt_rows = (
        sb.table("test_attempts")
        .select("user_id, started_at")
        .gte("started_at", since_14d)
        .execute()
    ).data or []
    for row in test_attempt_rows:
        uid = row.get("user_id")
        started = row.get("started_at")
        if not uid or not started:
            continue
        ts = _parse_dt(started)
        uid_str = str(uid)
        if ts >= _parse_dt(since_7d):
            active_user_ids.add(uid_str)
            idx = _bucket_index(buckets, ts)
            if idx is not None:
                buckets[idx]["active_users"].add(uid_str)
        elif ts >= _parse_dt(since_14d):
            prev_active_user_ids.add(uid_str)

    signup_rows = (
        sb.table("users")
        .select("created_at")
        .gte("created_at", since_7d)
        .execute()
    ).data or []
    for row in signup_rows:
        created = row.get("created_at")
        if not created:
            continue
        idx = _bucket_index(buckets, _parse_dt(created))
        if idx is not None:
            buckets[idx]["signups"] += 1

    weekly_activity = [
        DailyActivityPoint(
            label=b["label"],
            date=b["date"],
            active_users=len(b["active_users"]),
            signups=b["signups"],
            mock_attempts=b["mock_attempts"],
        )
        for b in buckets
    ]

    activity_candidates: list[RecentActivityItem] = []

    recent_users = (
        sb.table("users")
        .select("id, full_name, email, created_at")
        .order("created_at", desc=True)
        .limit(6)
        .execute()
    ).data or []
    for row in recent_users:
        name = row.get("full_name") or row.get("email") or "Someone"
        activity_candidates.append(
            RecentActivityItem(
                id=str(row["id"]),
                kind="signup",
                message=f"{name} registered",
                created_at=_parse_dt(row["created_at"]),
            )
        )

    recent_attempts = (
        sb.table("mock_attempts")
        .select("id, started_at, users(full_name, email), mock_tests(title)")
        .order("started_at", desc=True)
        .limit(6)
        .execute()
    ).data or []
    for row in recent_attempts:
        user = row.get("users") or {}
        mock = row.get("mock_tests") or {}
        name = user.get("full_name") or user.get("email") or "A student"
        title = mock.get("title") or "a mock test"
        activity_candidates.append(
            RecentActivityItem(
                id=str(row["id"]),
                kind="mock_attempt",
                message=f"{name} started {title}",
                created_at=_parse_dt(row["started_at"]),
            )
        )

    audit_rows = (
        sb.table("admin_audit_logs")
        .select("id, action, metadata, created_at")
        .order("created_at", desc=True)
        .limit(6)
        .execute()
    ).data or []
    for row in audit_rows:
        activity_candidates.append(
            RecentActivityItem(
                id=str(row["id"]),
                kind="admin",
                message=_format_audit_message(str(row["action"]), row.get("metadata")),
                created_at=_parse_dt(row["created_at"]),
            )
        )

    activity_candidates.sort(key=lambda item: item.created_at, reverse=True)
    recent_activity = activity_candidates[:8]

    metrics = DashboardMetrics(
        total_users=total_users,
        active_users_7d=len(active_user_ids),
        new_signups_7d=signups_7d,
        mock_attempts_7d=mock_attempts_7d,
        speaking_pending=speaking_pending,
        total_mocks=total_mocks,
        published_mocks=published_mocks,
        users_trend_pct=_trend_pct(len(active_user_ids), len(prev_active_user_ids)),
        signups_trend_pct=_trend_pct(signups_7d, signups_prev_7d),
        mocks_trend_pct=_trend_pct(mock_attempts_7d, mock_attempts_prev_7d),
    )

    return DashboardOverview(
        metrics=metrics,
        weekly_activity=weekly_activity,
        recent_activity=recent_activity,
    )


def get_dashboard_metrics() -> DashboardMetrics:
    """Backward-compatible metrics-only accessor."""
    return get_dashboard_overview().metrics
