"""Dashboard summary endpoints — stats, in-progress attempts, recent activity."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from time import perf_counter
from typing import Annotated, Any
from zoneinfo import ZoneInfo

APP_TZ = ZoneInfo("Asia/Kolkata")

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.cache.hybrid_cache import get_json, set_json
from app.db.supabase_client import execute_with_retry
from app.db.supabase_client import get_supabase
from uuid import UUID

from app.mock_catalog.catalog import is_full_mock_id
from app.services.user_activity import build_user_mock_sessions

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class MockTestRef(BaseModel):
    id: str
    title: str


class InProgressAttempt(BaseModel):
    id: str
    module: str
    started_at: datetime
    mock_test: MockTestRef


class RecentAttempt(BaseModel):
    id: str
    module: str
    started_at: datetime
    completed_at: datetime | None = None
    status: str
    band: float | None = None
    raw_score: int | None = None
    total_questions: int | None = None
    part: int | None = None
    mock_attempt_id: str | None = None
    mock_test: MockTestRef


class DashboardMockSnapshot(BaseModel):
    mock_attempt_id: str
    mock_test_id: str
    catalog_number: int | None = None
    status: str
    listening_band: float | None = None
    reading_band: float | None = None
    writing_band: float | None = None
    speaking_band: float | None = None
    aggregate_band: float | None = None


class ActivityDay(BaseModel):
    date: str  # YYYY-MM-DD in APP_TZ
    count: int = 0


class DashboardStats(BaseModel):
    total_attempts: int = 0
    completed_attempts: int = 0
    in_progress_attempts: int = 0
    average_band: float | None = None
    best_band: float | None = None
    last_activity_at: datetime | None = None
    current_streak: int = 0
    longest_streak: int = 0


class DashboardSummary(BaseModel):
    stats: DashboardStats
    in_progress: list[InProgressAttempt] = Field(default_factory=list)
    recent: list[RecentAttempt] = Field(default_factory=list)
    activity_days: list[ActivityDay] = Field(default_factory=list)
    completed_mock_count: int = 0
    latest_mock: DashboardMockSnapshot | None = None


def _round_half(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 2) / 2


def _to_app_date(dt: datetime) -> date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(APP_TZ).date()


def _streaks_from_counts(day_counts: dict[date, int]) -> tuple[int, int]:
    """Current consecutive streak (ending today) and longest streak."""
    if not day_counts:
        return 0, 0

    active_dates = sorted(d for d, c in day_counts.items() if c > 0)
    if not active_dates:
        return 0, 0

    longest = 1
    run = 1
    for i in range(1, len(active_dates)):
        if (active_dates[i] - active_dates[i - 1]).days == 1:
            run += 1
            longest = max(longest, run)
        else:
            run = 1

    today = datetime.now(APP_TZ).date()
    current = 0
    cursor = today
    while day_counts.get(cursor, 0) > 0:
        current += 1
        cursor -= timedelta(days=1)
    return current, longest


def _activity_calendar(day_counts: dict[date, int], *, days: int = 84) -> list[ActivityDay]:
    today = datetime.now(APP_TZ).date()
    start = today - timedelta(days=days - 1)
    out: list[ActivityDay] = []
    cursor = start
    while cursor <= today:
        out.append(
            ActivityDay(
                date=cursor.isoformat(),
                count=int(day_counts.get(cursor, 0)),
            )
        )
        cursor += timedelta(days=1)
    return out


def _safe_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> DashboardSummary:
    """Aggregate dashboard data for the current user."""
    request_started = perf_counter()
    client = get_supabase()
    user_id = str(current_user.id)
    cache_key = f"dashboard_summary:{user_id}"
    cached = get_json(cache_key)
    if isinstance(cached, dict):
        try:
            response = DashboardSummary.model_validate(cached)
            print(
                json.dumps(
                    {
                        "route": "/api/dashboard/summary",
                        "duration_ms": round((perf_counter() - request_started) * 1000, 2),
                        "cache_hit": True,
                        "cache_layer": "hybrid",
                        "status": 200,
                    }
                )
            )
            return response
        except Exception:
            pass

    attempts_res = execute_with_retry(lambda: (
        client.table("test_attempts")
        .select(
            "id, module, status, started_at, completed_at, mock_test_id, part, mock_attempt_id"
        )
        .eq("user_id", user_id)
        .order("started_at", desc=True)
        .limit(50)
        .execute()
    ))
    attempts: list[dict[str, Any]] = list(attempts_res.data or [])

    mock_ids = sorted({a["mock_test_id"] for a in attempts if a.get("mock_test_id")})
    mocks_by_id: dict[str, dict[str, Any]] = {}
    if mock_ids:
        mocks_res = execute_with_retry(lambda: (
            client.table("mock_tests")
            .select("id, title")
            .in_("id", mock_ids)
            .execute()
        ))
        for row in mocks_res.data or []:
            mocks_by_id[str(row["id"])] = row

    attempt_ids = [a["id"] for a in attempts]
    scores_by_attempt: dict[str, dict[str, Any]] = {}
    if attempt_ids:
        scores_res = execute_with_retry(lambda: (
            client.table("module_scores")
            .select("attempt_id, band, raw_score, total_count")
            .in_("attempt_id", attempt_ids)
            .execute()
        ))
        for row in scores_res.data or []:
            scores_by_attempt[str(row["attempt_id"])] = row

    writing_reviews_by_attempt: dict[str, dict[str, Any]] = {}
    if attempt_ids:
        writing_res = execute_with_retry(lambda: (
            client.table("writing_reviews")
            .select("attempt_id, status, human_band, ai_scores, created_at")
            .in_("attempt_id", attempt_ids)
            .order("created_at", desc=True)
            .execute()
        ))
        for row in writing_res.data or []:
            aid = str(row.get("attempt_id") or "")
            if not aid or aid in writing_reviews_by_attempt:
                continue
            writing_reviews_by_attempt[aid] = row

    speaking_reviews_by_attempt: dict[str, dict[str, Any]] = {}
    if attempt_ids:
        speaking_res = execute_with_retry(lambda: (
            client.table("speaking_reviews")
            .select("attempt_id, status, human_band, created_at")
            .in_("attempt_id", attempt_ids)
            .order("created_at", desc=True)
            .execute()
        ))
        for row in speaking_res.data or []:
            aid = str(row.get("attempt_id") or "")
            if not aid or aid in speaking_reviews_by_attempt:
                continue
            speaking_reviews_by_attempt[aid] = row

    bands: list[float] = []
    in_progress: list[InProgressAttempt] = []
    recent: list[RecentAttempt] = []
    last_activity: datetime | None = None
    completed_count = 0
    day_counts: dict[date, int] = {}

    for a in attempts:
        attempt_started = _safe_dt(a.get("started_at"))
        completed = _safe_dt(a.get("completed_at"))
        latest_dt = completed or attempt_started
        if latest_dt and (last_activity is None or latest_dt > last_activity):
            last_activity = latest_dt

        mock_row = mocks_by_id.get(str(a.get("mock_test_id") or ""))
        mock_ref = MockTestRef(
            id=str(a.get("mock_test_id") or ""),
            title=str(mock_row["title"]) if mock_row else "Untitled mock",
        )
        status_lc = str(a.get("status") or "").lower()

        module = str(a.get("module") or "")
        mock_id = str(a.get("mock_test_id") or "")
        if not is_full_mock_id(mock_id):
            continue

        if status_lc == "in_progress" and attempt_started:
            in_progress.append(
                InProgressAttempt(
                    id=str(a["id"]),
                    module=module,
                    started_at=attempt_started,
                    mock_test=mock_ref,
                )
            )

        if status_lc == "completed":
            completed_count += 1
            activity_dt = completed or attempt_started
            if activity_dt:
                d = _to_app_date(activity_dt)
                day_counts[d] = day_counts.get(d, 0) + 1
            score = scores_by_attempt.get(str(a["id"]))
            review_writing = writing_reviews_by_attempt.get(str(a["id"]))
            review_speaking = speaking_reviews_by_attempt.get(str(a["id"]))
            band_val = (
                _safe_float(score.get("band")) if score else None
            )
            if band_val is None and module == "writing" and review_writing:
                band_val = _safe_float(review_writing.get("human_band"))
                if band_val is None:
                    ai_scores = review_writing.get("ai_scores")
                    if isinstance(ai_scores, dict):
                        band_val = _safe_float(ai_scores.get("word_count_estimate"))
            if band_val is None and module == "speaking" and review_speaking:
                band_val = _safe_float(review_speaking.get("human_band"))
            if band_val is not None and band_val > 0:
                bands.append(band_val)
            part_raw = a.get("part")
            part_val = int(part_raw) if part_raw is not None else None
            mock_attempt_raw = a.get("mock_attempt_id")
            recent.append(
                RecentAttempt(
                    id=str(a["id"]),
                    module=module,
                    started_at=attempt_started or datetime.now(UTC),
                    completed_at=completed,
                    status="completed",
                    band=band_val,
                    raw_score=int(score["raw_score"]) if score and score.get("raw_score") is not None else None,
                    total_questions=int(score["total_count"])
                    if score and score.get("total_count") is not None
                    else None,
                    part=part_val,
                    mock_attempt_id=str(mock_attempt_raw) if mock_attempt_raw else None,
                    mock_test=mock_ref,
                )
            )

    in_progress.sort(key=lambda x: x.started_at, reverse=True)
    recent.sort(
        key=lambda x: (x.completed_at or x.started_at),
        reverse=True,
    )

    avg = sum(bands) / len(bands) if bands else None
    best = max(bands) if bands else None
    current_streak, longest_streak = _streaks_from_counts(day_counts)

    mock_sessions = build_user_mock_sessions(UUID(user_id))
    completed_mock_count = sum(
        1 for s in mock_sessions if str(s.get("status") or "").lower() == "completed"
    )
    latest_mock_row = mock_sessions[0] if mock_sessions else None
    latest_mock: DashboardMockSnapshot | None = None
    if latest_mock_row:
        latest_mock = DashboardMockSnapshot(
            mock_attempt_id=str(latest_mock_row["mock_attempt_id"]),
            mock_test_id=str(latest_mock_row["mock_test_id"]),
            catalog_number=(
                int(latest_mock_row["catalog_number"])
                if latest_mock_row.get("catalog_number") is not None
                else None
            ),
            status=str(latest_mock_row.get("status") or ""),
            listening_band=_round_half(latest_mock_row.get("listening_band")),
            reading_band=_round_half(latest_mock_row.get("reading_band")),
            writing_band=_round_half(latest_mock_row.get("writing_band")),
            speaking_band=_round_half(latest_mock_row.get("speaking_band")),
            aggregate_band=_round_half(latest_mock_row.get("aggregate_band")),
        )

    response = DashboardSummary(
        stats=DashboardStats(
            total_attempts=len(attempts),
            completed_attempts=completed_count,
            in_progress_attempts=len(in_progress),
            average_band=_round_half(avg),
            best_band=_round_half(best),
            last_activity_at=last_activity,
            current_streak=current_streak,
            longest_streak=longest_streak,
        ),
        in_progress=in_progress[:5],
        recent=recent,
        activity_days=_activity_calendar(day_counts),
        completed_mock_count=completed_mock_count,
        latest_mock=latest_mock,
    )
    set_json(cache_key, response.model_dump(mode="json"), ttl_seconds=20)
    print(
        json.dumps(
            {
                "route": "/api/dashboard/summary",
                "duration_ms": round((perf_counter() - request_started) * 1000, 2),
                "cache_hit": False,
                "cache_layer": "none",
                "status": 200,
            }
        )
    )
    return response
