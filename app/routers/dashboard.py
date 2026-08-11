"""Dashboard summary endpoints — stats, in-progress attempts, recent activity."""

from __future__ import annotations

import json
import math
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
from app.services.user_activity import (
    activity_calendar as ua_activity_calendar,
    build_user_activity_day_counts,
    build_user_mock_sessions,
    streaks_from_counts,
    week_active_days,
)

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
    score_source: str = "unavailable"
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
    return streaks_from_counts(day_counts)


def _activity_calendar(day_counts: dict[date, int], *, days: int = 84) -> list[ActivityDay]:
    return [
        ActivityDay(date=row["date"], count=int(row["count"]))
        for row in ua_activity_calendar(day_counts, days=days)
    ]


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


def _completed_ai_band(review: dict[str, Any] | None) -> float | None:
    """Return only a completed, valid provisional AI band from a review."""
    if not review:
        return None
    ai_scores = review.get("ai_scores")
    if not isinstance(ai_scores, dict):
        return None
    ai_status = str(ai_scores.get("status") or "").lower()
    evaluation_status = str(review.get("evaluation_status") or "").lower()
    if ai_status not in {"ai_complete", "ai_stub"} and evaluation_status != "completed":
        return None
    band = _safe_float(ai_scores.get("ai_band"))
    if (
        band is None
        or not math.isfinite(band)
        or band < 0
        or band > 9
        or band * 2 != int(band * 2)
    ):
        return None
    return band


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
            .select(
                "attempt_id, status, human_band, ai_scores, evaluation_status, created_at"
            )
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
            score = scores_by_attempt.get(str(a["id"]))
            review_writing = writing_reviews_by_attempt.get(str(a["id"]))
            review_speaking = speaking_reviews_by_attempt.get(str(a["id"]))
            score_source = "unavailable"
            band_val = (
                _safe_float(score.get("band")) if score else None
            )
            if band_val is not None:
                score_source = "module_score"
            if band_val is None and module == "writing" and review_writing:
                band_val = _safe_float(review_writing.get("human_band"))
                if band_val is None:
                    band_val = _completed_ai_band(review_writing)
                    if band_val is not None:
                        score_source = "ai_estimate"
                else:
                    score_source = "human"
            if band_val is None and module == "speaking" and review_speaking:
                band_val = _safe_float(review_speaking.get("human_band"))
                if band_val is None:
                    band_val = _completed_ai_band(review_speaking)
                    if band_val is not None:
                        score_source = "ai_estimate"
                else:
                    score_source = "human"
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
                    score_source=score_source,
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
    day_counts = build_user_activity_day_counts(UUID(user_id))
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


class ActivityDayLite(BaseModel):
    date: str
    count: int = 0


class DashboardStreak(BaseModel):
    current_streak: int = 0
    longest_streak: int = 0
    activity_days: list[ActivityDayLite] = Field(default_factory=list)
    week_active_days: int = 0
    prep_start: str | None = None
    exam_date: str | None = None


def _parse_iso_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _load_prep_window(user_id: str) -> tuple[date | None, date | None]:
    """prep_start → exam_date from the learning profile, then users.exam_date."""
    client = get_supabase()
    prep: date | None = None
    exam: date | None = None
    try:
        res = execute_with_retry(
            lambda: (
                client.table("user_learning_profiles")
                .select("prep_start, exam_date, study_plan")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
        )
        row = (res.data or [None])[0] or {}
        plan = row.get("study_plan") if isinstance(row.get("study_plan"), dict) else {}
        prep = _parse_iso_date(row.get("prep_start")) or _parse_iso_date(
            plan.get("prep_start")
        )
        exam = _parse_iso_date(row.get("exam_date")) or _parse_iso_date(
            plan.get("exam_date")
        )
    except Exception:
        pass
    if exam is None:
        try:
            ures = execute_with_retry(
                lambda: (
                    client.table("users")
                    .select("exam_date")
                    .eq("id", user_id)
                    .limit(1)
                    .execute()
                )
            )
            urow = (ures.data or [None])[0] or {}
            exam = _parse_iso_date(urow.get("exam_date"))
        except Exception:
            pass
    return prep, exam


def _activity_span(
    day_counts: dict[date, int], start: date, end: date
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor = start
    while cursor <= end:
        out.append({"date": cursor.isoformat(), "count": int(day_counts.get(cursor, 0))})
        cursor += timedelta(days=1)
    return out


@router.get("/streak", response_model=DashboardStreak)
def dashboard_streak(
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> DashboardStreak:
    """Streak + heatmap from prep start through the user's exam date."""
    request_started = perf_counter()
    user_id = str(current_user.id)
    cache_key = f"dashboard_streak:v2:{user_id}"
    cached = get_json(cache_key)
    if isinstance(cached, dict):
        try:
            response = DashboardStreak.model_validate(cached)
            print(
                json.dumps(
                    {
                        "route": "/api/dashboard/streak",
                        "duration_ms": round(
                            (perf_counter() - request_started) * 1000, 2
                        ),
                        "cache_hit": True,
                        "cache_layer": "hybrid",
                        "status": 200,
                    }
                )
            )
            return response
        except Exception:
            pass

    day_counts = build_user_activity_day_counts(UUID(user_id))
    current_streak, longest_streak = streaks_from_counts(day_counts)
    today = datetime.now(APP_TZ).date()
    prep, exam = _load_prep_window(user_id)
    start = prep or (today - timedelta(days=55))
    end = exam or today
    if end < start:
        start = end
    max_days = 120
    if (end - start).days + 1 > max_days:
        if end >= today:
            end = min(end, today + timedelta(days=max_days - 1))
            start = max(start, end - timedelta(days=max_days - 1))
            start = min(start, today)
        else:
            end = min(end, today)
            start = end - timedelta(days=max_days - 1)
    cal = _activity_span(day_counts, start, end)
    response = DashboardStreak(
        current_streak=current_streak,
        longest_streak=longest_streak,
        activity_days=[ActivityDayLite(**row) for row in cal],
        week_active_days=week_active_days(day_counts),
        prep_start=prep.isoformat() if prep else None,
        exam_date=exam.isoformat() if exam else None,
    )
    set_json(cache_key, response.model_dump(mode="json"), ttl_seconds=30)
    print(
        json.dumps(
            {
                "route": "/api/dashboard/streak",
                "duration_ms": round((perf_counter() - request_started) * 1000, 2),
                "cache_hit": False,
                "cache_layer": "none",
                "status": 200,
            }
        )
    )
    return response
