"""Admin CSV export helpers (Phase 6.6)."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable, Iterator, Literal

from fastapi.responses import StreamingResponse

from app.admin import review_analytics as admin_review_analytics
from app.admin import users as admin_users
from app.db.supabase_client import get_supabase


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _streaming_csv(
    *,
    filename: str,
    fieldnames: list[str],
    rows: Iterable[dict[str, Any]],
) -> StreamingResponse:
    def generate() -> Iterator[str]:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
    }
    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


def review_analytics_csv(
    *,
    module: Literal["speaking", "writing", "all"] = "all",
    days: int = 30,
) -> StreamingResponse:
    data = admin_review_analytics.get_review_analytics(module=module, days=days)
    rows: list[dict[str, Any]] = [
        {
            "section": "summary",
            "module": data.module,
            "days": data.days,
            "completed": data.completed,
            "agreement_rate": data.agreement_rate,
            "override_rate": data.override_rate,
            "overall_mae": data.overall_mae,
            "with_ai": data.with_ai,
            "without_ai": data.without_ai,
            "criterion_key": "",
            "criterion_label": "",
            "mae": "",
            "sample_count": "",
        }
    ]
    for item in data.criterion_mae:
        rows.append(
            {
                "section": "criterion",
                "module": data.module,
                "days": data.days,
                "completed": "",
                "agreement_rate": "",
                "override_rate": "",
                "overall_mae": "",
                "with_ai": "",
                "without_ai": "",
                "criterion_key": item.key,
                "criterion_label": item.label,
                "mae": item.mae,
                "sample_count": item.sample_count,
            }
        )
    return _streaming_csv(
        filename=f"review-analytics-{module}-{days}d.csv",
        fieldnames=[
            "section",
            "module",
            "days",
            "completed",
            "agreement_rate",
            "override_rate",
            "overall_mae",
            "with_ai",
            "without_ai",
            "criterion_key",
            "criterion_label",
            "mae",
            "sample_count",
        ],
        rows=rows,
    )


def users_overview_csv(*, page_size: int = 500) -> StreamingResponse:
    page_size = max(1, min(page_size, 1000))
    page = 1
    collected: list[dict[str, Any]] = []
    while True:
        batch = admin_users.list_users(page=page, page_size=page_size)
        for item in batch.items:
            collected.append(
                {
                    "id": str(item.id),
                    "email": item.email or "",
                    "full_name": item.full_name or "",
                    "role": item.role,
                    "is_active": item.is_active,
                    "created_at": _iso(item.created_at),
                    "mock_attempt_count": item.mock_attempt_count,
                    "completed_mock_count": item.completed_mock_count,
                    "last_activity_at": _iso(item.last_activity_at),
                    "best_band": item.best_band if item.best_band is not None else "",
                }
            )
        if page * page_size >= batch.total or not batch.items:
            break
        page += 1
        if page > 50:
            break
    return _streaming_csv(
        filename="users-overview.csv",
        fieldnames=[
            "id",
            "email",
            "full_name",
            "role",
            "is_active",
            "created_at",
            "mock_attempt_count",
            "completed_mock_count",
            "last_activity_at",
            "best_band",
        ],
        rows=collected,
    )


def reliability_snapshot_csv() -> StreamingResponse:
    from app.reliability.metrics import snapshot

    snap = snapshot()
    rows: list[dict[str, Any]] = []
    day = snap.get("day", "")
    counters = snap.get("counters") if isinstance(snap.get("counters"), dict) else {}
    for key, value in counters.items():
        rows.append(
            {
                "section": "counter",
                "day": day,
                "key": key,
                "value": value,
                "route": "",
                "n": "",
                "p50_ms": "",
                "p95_ms": "",
                "event_ts": "",
                "event_kind": "",
                "event_detail": "",
            }
        )
    rows.append(
        {
            "section": "summary",
            "day": day,
            "key": "completion_rate",
            "value": snap.get("completion_rate"),
            "route": "",
            "n": "",
            "p50_ms": "",
            "p95_ms": "",
            "event_ts": "",
            "event_kind": "",
            "event_detail": "",
        }
    )
    latency = snap.get("latency") if isinstance(snap.get("latency"), dict) else {}
    for route, stats in latency.items():
        if not isinstance(stats, dict):
            continue
        rows.append(
            {
                "section": "latency",
                "day": day,
                "key": "",
                "value": "",
                "route": route,
                "n": stats.get("n"),
                "p50_ms": stats.get("p50_ms"),
                "p95_ms": stats.get("p95_ms"),
                "event_ts": "",
                "event_kind": "",
                "event_detail": "",
            }
        )
    practice = snap.get("practice") if isinstance(snap.get("practice"), dict) else {}
    for skill, count in (practice.get("hubs_by_skill") or {}).items():
        rows.append(
            {
                "section": "practice_hubs",
                "day": day,
                "key": skill,
                "value": count,
                "route": "",
                "n": "",
                "p50_ms": "",
                "p95_ms": "",
                "event_ts": "",
                "event_kind": "",
                "event_detail": "",
            }
        )
    if "hub_completions_7d" in practice:
        rows.append(
            {
                "section": "practice",
                "day": day,
                "key": "hub_completions_7d",
                "value": practice.get("hub_completions_7d"),
                "route": "",
                "n": "",
                "p50_ms": "",
                "p95_ms": "",
                "event_ts": "",
                "event_kind": "",
                "event_detail": "",
            }
        )
    notifications = (
        snap.get("notifications") if isinstance(snap.get("notifications"), dict) else {}
    )
    for key in ("queued", "failed_24h"):
        if key in notifications:
            rows.append(
                {
                    "section": "notifications",
                    "day": day,
                    "key": key,
                    "value": notifications.get(key),
                    "route": "",
                    "n": "",
                    "p50_ms": "",
                    "p95_ms": "",
                    "event_ts": "",
                    "event_kind": "",
                    "event_detail": "",
                }
            )
    for event in snap.get("recent_events") or []:
        if not isinstance(event, dict):
            continue
        rows.append(
            {
                "section": "event",
                "day": day,
                "key": "",
                "value": "",
                "route": "",
                "n": "",
                "p50_ms": "",
                "p95_ms": "",
                "event_ts": event.get("ts") or "",
                "event_kind": event.get("kind") or event.get("event") or "",
                "event_detail": event.get("detail") or "",
            }
        )
    return _streaming_csv(
        filename="reliability-snapshot.csv",
        fieldnames=[
            "section",
            "day",
            "key",
            "value",
            "route",
            "n",
            "p50_ms",
            "p95_ms",
            "event_ts",
            "event_kind",
            "event_detail",
        ],
        rows=rows,
    )


def hub_progress_7d_csv() -> StreamingResponse:
    since = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    sb = get_supabase()
    rows_out: list[dict[str, Any]] = []
    offset = 0
    page = 500
    while True:
        result = (
            sb.table("user_hub_progress")
            .select("id, user_id, hub_id, status, completed_at, updated_at")
            .eq("status", "completed")
            .gte("completed_at", since)
            .order("completed_at", desc=True)
            .range(offset, offset + page - 1)
            .execute()
        )
        batch = result.data or []
        for row in batch:
            if not isinstance(row, dict):
                continue
            rows_out.append(
                {
                    "id": row.get("id") or "",
                    "user_id": row.get("user_id") or "",
                    "hub_id": row.get("hub_id") or "",
                    "status": row.get("status") or "",
                    "completed_at": row.get("completed_at") or "",
                    "updated_at": row.get("updated_at") or "",
                }
            )
        if len(batch) < page:
            break
        offset += page
        if offset > 20_000:
            break
    return _streaming_csv(
        filename="hub-progress-7d.csv",
        fieldnames=[
            "id",
            "user_id",
            "hub_id",
            "status",
            "completed_at",
            "updated_at",
        ],
        rows=rows_out,
    )
