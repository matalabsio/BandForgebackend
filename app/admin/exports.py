"""Admin CSV export helpers (Phase 6.6)."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Iterable, Iterator, Literal

from fastapi.responses import StreamingResponse

from app.admin import review_analytics as admin_review_analytics
from app.admin import users as admin_users


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
