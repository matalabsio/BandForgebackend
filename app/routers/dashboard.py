"""Dashboard summary endpoints — stats, in-progress attempts, recent activity."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.db.supabase_client import get_supabase
from app.listening.constants import LISTENING_TEST_ID

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
    mock_test: MockTestRef


class DashboardStats(BaseModel):
    total_attempts: int = 0
    completed_attempts: int = 0
    in_progress_attempts: int = 0
    average_band: float | None = None
    best_band: float | None = None
    last_activity_at: datetime | None = None


class DashboardSummary(BaseModel):
    stats: DashboardStats
    in_progress: list[InProgressAttempt] = Field(default_factory=list)
    recent: list[RecentAttempt] = Field(default_factory=list)


def _round_half(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 2) / 2


def _safe_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> DashboardSummary:
    """Aggregate dashboard data for the current user."""
    client = get_supabase()
    user_id = str(current_user.id)

    attempts_res = (
        client.table("test_attempts")
        .select("id, module, status, started_at, completed_at, mock_test_id")
        .eq("user_id", user_id)
        .order("started_at", desc=True)
        .limit(50)
        .execute()
    )
    attempts: list[dict[str, Any]] = list(attempts_res.data or [])

    mock_ids = sorted({a["mock_test_id"] for a in attempts if a.get("mock_test_id")})
    mocks_by_id: dict[str, dict[str, Any]] = {}
    if mock_ids:
        mocks_res = (
            client.table("mock_tests")
            .select("id, title")
            .in_("id", mock_ids)
            .execute()
        )
        for row in mocks_res.data or []:
            mocks_by_id[str(row["id"])] = row

    attempt_ids = [a["id"] for a in attempts]
    scores_by_attempt: dict[str, dict[str, Any]] = {}
    if attempt_ids:
        scores_res = (
            client.table("module_scores")
            .select("attempt_id, band, raw_score, total_count")
            .in_("attempt_id", attempt_ids)
            .execute()
        )
        for row in scores_res.data or []:
            scores_by_attempt[str(row["attempt_id"])] = row

    bands: list[float] = []
    in_progress: list[InProgressAttempt] = []
    recent: list[RecentAttempt] = []
    last_activity: datetime | None = None
    completed_count = 0

    for a in attempts:
        started = _safe_dt(a.get("started_at"))
        completed = _safe_dt(a.get("completed_at"))
        latest_dt = completed or started
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
        if module == "listening" and mock_id != LISTENING_TEST_ID:
            continue

        if status_lc == "in_progress" and started:
            in_progress.append(
                InProgressAttempt(
                    id=str(a["id"]),
                    module=module,
                    started_at=started,
                    mock_test=mock_ref,
                )
            )

        if status_lc == "completed":
            completed_count += 1
            score = scores_by_attempt.get(str(a["id"]))
            band_val = float(score["band"]) if score and score.get("band") is not None else None
            if band_val is not None:
                bands.append(band_val)
            recent.append(
                RecentAttempt(
                    id=str(a["id"]),
                    module=module,
                    started_at=started or datetime.now(UTC),
                    completed_at=completed,
                    status="completed",
                    band=band_val,
                    raw_score=int(score["raw_score"]) if score and score.get("raw_score") is not None else None,
                    total_questions=int(score["total_count"])
                    if score and score.get("total_count") is not None
                    else None,
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

    return DashboardSummary(
        stats=DashboardStats(
            total_attempts=len(attempts),
            completed_attempts=completed_count,
            in_progress_attempts=len(in_progress),
            average_band=_round_half(avg),
            best_band=_round_half(best),
            last_activity_at=last_activity,
        ),
        in_progress=in_progress[:5],
        recent=recent[:8],
    )
