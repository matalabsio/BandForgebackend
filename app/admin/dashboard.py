"""Admin dashboard metrics and activity feed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.admin.parallel import run_parallel
from app.admin.schemas import (
    DailyActivityPoint,
    DashboardMetrics,
    DashboardOverview,
    RecentActivityItem,
)
from app.db.supabase_client import get_supabase
from app.mock_catalog.constants import (
    MAX_CANDIDATE_CATALOG_NUMBER,
    is_candidate_live_catalog_number,
)
from app.perf.timing import timed_call, timed_supabase


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


def _fetch_counts(since_7d: str, since_14d: str) -> dict[str, int]:
    def total_users() -> int:
        return timed_supabase(
            "dashboard.users.total",
            lambda: get_supabase().table("users").select("id", count="exact").execute(),
        ).count or 0

    def signups_7d() -> int:
        return timed_supabase(
            "dashboard.users.signups_7d",
            lambda: (
                get_supabase()
                .table("users")
                .select("id", count="exact")
                .gte("created_at", since_7d)
                .execute()
            ),
        ).count or 0

    def signups_prev_7d() -> int:
        return timed_supabase(
            "dashboard.users.signups_prev_7d",
            lambda: (
                get_supabase()
                .table("users")
                .select("id", count="exact")
                .gte("created_at", since_14d)
                .lt("created_at", since_7d)
                .execute()
            ),
        ).count or 0

    def mock_attempts_7d() -> int:
        return timed_supabase(
            "dashboard.mock_attempts.count_7d",
            lambda: (
                get_supabase()
                .table("mock_attempts")
                .select("id", count="exact")
                .gte("started_at", since_7d)
                .execute()
            ),
        ).count or 0

    def mock_attempts_prev_7d() -> int:
        return timed_supabase(
            "dashboard.mock_attempts.count_prev_7d",
            lambda: (
                get_supabase()
                .table("mock_attempts")
                .select("id", count="exact")
                .gte("started_at", since_14d)
                .lt("started_at", since_7d)
                .execute()
            ),
        ).count or 0

    def speaking_pending() -> int:
        return timed_supabase(
            "dashboard.speaking_reviews.pending",
            lambda: (
                get_supabase()
                .table("speaking_reviews")
                .select("id", count="exact")
                .eq("status", "pending")
                .execute()
            ),
        ).count or 0

    def writing_pending_mock() -> int:
        try:
            return timed_supabase(
                "dashboard.writing_reviews.pending",
                lambda: (
                    get_supabase()
                    .table("writing_reviews")
                    .select("id", count="exact")
                    .eq("status", "pending")
                    .execute()
                ),
            ).count or 0
        except Exception:
            return 0

    def writing_pending_diag() -> int:
        try:
            return timed_supabase(
                "dashboard.diagnostic_reviews.pending",
                lambda: (
                    get_supabase()
                    .table("diagnostic_review_submissions")
                    .select("id", count="exact")
                    .eq("status", "pending_review")
                    .execute()
                ),
            ).count or 0
        except Exception:
            return 0

    def published_mocks() -> int:
        rows = timed_supabase(
            "dashboard.mock_tests.catalog",
            lambda: (
                get_supabase()
                .table("mock_tests")
                .select("id, status, catalog_number")
                .not_.is_("catalog_number", "null")
                .execute()
            ),
        ).data or []
        live = [
            r for r in rows if is_candidate_live_catalog_number(r.get("catalog_number"))
        ]
        return sum(1 for r in live if r.get("status") == "published")

    results = timed_call(
        "dashboard.counts_parallel",
        lambda: run_parallel(
            {
                "total_users": total_users,
                "signups_7d": signups_7d,
                "signups_prev_7d": signups_prev_7d,
                "mock_attempts_7d": mock_attempts_7d,
                "mock_attempts_prev_7d": mock_attempts_prev_7d,
                "speaking_pending": speaking_pending,
                "writing_pending_mock": writing_pending_mock,
                "writing_pending_diag": writing_pending_diag,
                "published_mocks": published_mocks,
            }
        ),
    )
    writing_pending = int(results["writing_pending_mock"]) + int(
        results["writing_pending_diag"]
    )
    return {
        "total_users": int(results["total_users"]),
        "signups_7d": int(results["signups_7d"]),
        "signups_prev_7d": int(results["signups_prev_7d"]),
        "mock_attempts_7d": int(results["mock_attempts_7d"]),
        "mock_attempts_prev_7d": int(results["mock_attempts_prev_7d"]),
        "speaking_pending": int(results["speaking_pending"]),
        "writing_pending": writing_pending,
        "published_mocks": int(results["published_mocks"]),
    }


def _fetch_activity_rows(since_7d: str, since_14d: str) -> dict[str, list[dict[str, Any]]]:
    def attempt_rows() -> list[dict[str, Any]]:
        return timed_supabase(
            "dashboard.mock_attempts.rows_14d",
            lambda: (
                get_supabase()
                .table("mock_attempts")
                .select("user_id, started_at")
                .gte("started_at", since_14d)
                .execute()
            ),
        ).data or []

    def test_attempt_rows() -> list[dict[str, Any]]:
        return timed_supabase(
            "dashboard.test_attempts.rows_14d",
            lambda: (
                get_supabase()
                .table("test_attempts")
                .select("user_id, started_at")
                .gte("started_at", since_14d)
                .execute()
            ),
        ).data or []

    def signup_rows() -> list[dict[str, Any]]:
        return timed_supabase(
            "dashboard.users.signup_rows_7d",
            lambda: (
                get_supabase()
                .table("users")
                .select("created_at")
                .gte("created_at", since_7d)
                .execute()
            ),
        ).data or []

    return timed_call(
        "dashboard.activity_parallel",
        lambda: run_parallel(
            {
                "attempt_rows": attempt_rows,
                "test_attempt_rows": test_attempt_rows,
                "signup_rows": signup_rows,
            }
        ),
    )


def _build_metrics_core(
    *,
    counts: dict[str, int],
    since_7d: str,
    since_14d: str,
) -> tuple[DashboardMetrics, list[DailyActivityPoint]]:
    since_7d_dt = _parse_dt(since_7d)
    since_14d_dt = _parse_dt(since_14d)
    active_user_ids: set[str] = set()
    prev_active_user_ids: set[str] = set()
    buckets = _day_buckets()

    activity = _fetch_activity_rows(since_7d, since_14d)

    for row in activity["attempt_rows"]:
        uid = row.get("user_id")
        started = row.get("started_at")
        if not uid or not started:
            continue
        ts = _parse_dt(started)
        uid_str = str(uid)
        if ts >= since_7d_dt:
            active_user_ids.add(uid_str)
            idx = _bucket_index(buckets, ts)
            if idx is not None:
                buckets[idx]["mock_attempts"] += 1
                buckets[idx]["active_users"].add(uid_str)
        elif ts >= since_14d_dt:
            prev_active_user_ids.add(uid_str)

    for row in activity["test_attempt_rows"]:
        uid = row.get("user_id")
        started = row.get("started_at")
        if not uid or not started:
            continue
        ts = _parse_dt(started)
        uid_str = str(uid)
        if ts >= since_7d_dt:
            active_user_ids.add(uid_str)
            idx = _bucket_index(buckets, ts)
            if idx is not None:
                buckets[idx]["active_users"].add(uid_str)
        elif ts >= since_14d_dt:
            prev_active_user_ids.add(uid_str)

    for row in activity["signup_rows"]:
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

    metrics = DashboardMetrics(
        total_users=counts["total_users"],
        active_users_7d=len(active_user_ids),
        new_signups_7d=counts["signups_7d"],
        mock_attempts_7d=counts["mock_attempts_7d"],
        speaking_pending=counts["speaking_pending"],
        writing_pending=counts["writing_pending"],
        total_mocks=MAX_CANDIDATE_CATALOG_NUMBER,
        published_mocks=counts["published_mocks"],
        users_trend_pct=_trend_pct(len(active_user_ids), len(prev_active_user_ids)),
        signups_trend_pct=_trend_pct(counts["signups_7d"], counts["signups_prev_7d"]),
        mocks_trend_pct=_trend_pct(
            counts["mock_attempts_7d"], counts["mock_attempts_prev_7d"]
        ),
    )
    return metrics, weekly_activity


def _fetch_recent_activity() -> list[RecentActivityItem]:
    def recent_users() -> list[dict[str, Any]]:
        return timed_supabase(
            "dashboard.users.recent",
            lambda: (
                get_supabase()
                .table("users")
                .select("id, full_name, email, created_at")
                .order("created_at", desc=True)
                .limit(6)
                .execute()
            ),
        ).data or []

    def recent_attempts() -> list[dict[str, Any]]:
        return timed_supabase(
            "dashboard.mock_attempts.recent",
            lambda: (
                get_supabase()
                .table("mock_attempts")
                .select("id, started_at, users(full_name, email), mock_tests(title)")
                .order("started_at", desc=True)
                .limit(6)
                .execute()
            ),
        ).data or []

    def audit_rows() -> list[dict[str, Any]]:
        return timed_supabase(
            "dashboard.audit.recent",
            lambda: (
                get_supabase()
                .table("admin_audit_logs")
                .select("id, action, metadata, created_at")
                .order("created_at", desc=True)
                .limit(6)
                .execute()
            ),
        ).data or []

    fetched = timed_call(
        "dashboard.recent_parallel",
        lambda: run_parallel(
            {
                "recent_users": recent_users,
                "recent_attempts": recent_attempts,
                "audit_rows": audit_rows,
            }
        ),
    )

    activity_candidates: list[RecentActivityItem] = []
    for row in fetched["recent_users"]:
        name = row.get("full_name") or row.get("email") or "Someone"
        activity_candidates.append(
            RecentActivityItem(
                id=str(row["id"]),
                kind="signup",
                message=f"{name} registered",
                created_at=_parse_dt(row["created_at"]),
            )
        )
    for row in fetched["recent_attempts"]:
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
    for row in fetched["audit_rows"]:
        activity_candidates.append(
            RecentActivityItem(
                id=str(row["id"]),
                kind="admin",
                message=_format_audit_message(str(row["action"]), row.get("metadata")),
                created_at=_parse_dt(row["created_at"]),
            )
        )

    activity_candidates.sort(key=lambda item: item.created_at, reverse=True)
    return activity_candidates[:8]


def get_dashboard_overview() -> DashboardOverview:
    now = datetime.now(UTC)
    since_7d = (now - timedelta(days=7)).isoformat()
    since_14d = (now - timedelta(days=14)).isoformat()

    counts = _fetch_counts(since_7d, since_14d)
    metrics, weekly_activity = _build_metrics_core(
        counts=counts,
        since_7d=since_7d,
        since_14d=since_14d,
    )
    recent_activity = _fetch_recent_activity()

    return DashboardOverview(
        metrics=metrics,
        weekly_activity=weekly_activity,
        recent_activity=recent_activity,
    )


def get_dashboard_metrics() -> DashboardMetrics:
    """Metrics-only path — skips recent activity feed fetches."""
    now = datetime.now(UTC)
    since_7d = (now - timedelta(days=7)).isoformat()
    since_14d = (now - timedelta(days=14)).isoformat()

    counts = _fetch_counts(since_7d, since_14d)
    metrics, _weekly = _build_metrics_core(
        counts=counts,
        since_7d=since_7d,
        since_14d=since_14d,
    )
    return metrics
