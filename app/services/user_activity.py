"""Shared user activity aggregation for dashboard and admin."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from app.db.supabase_client import execute_with_retry, get_supabase
from app.mock_catalog.catalog import is_full_mock_id
from app.services import mock_orchestrator_repository as repo
from app.services.mock_orchestrator import _module_rollup_band_from_scores

APP_TZ = ZoneInfo("Asia/Kolkata")


def _safe_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _parse_dt(value: Any) -> datetime:
    dt = _safe_dt(value)
    if dt is None:
        raise ValueError(f"Invalid datetime: {value!r}")
    return dt


def _to_app_date(dt: datetime) -> date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(APP_TZ).date()


def _round_half(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 2) / 2


def streaks_from_counts(day_counts: dict[date, int]) -> tuple[int, int]:
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


# Back-compat alias
_streaks_from_counts = streaks_from_counts


def _bump(day_counts: dict[date, int], d: date, n: int = 1) -> None:
    day_counts[d] = day_counts.get(d, 0) + n


def build_user_activity_day_counts(user_id: UUID) -> dict[date, int]:
    """Union of mock completions + plan/hub practice days (Asia/Kolkata)."""
    client = get_supabase()
    uid = str(user_id)
    day_counts: dict[date, int] = {}

    attempts_res = execute_with_retry(
        lambda: (
            client.table("test_attempts")
            .select("status, started_at, completed_at, mock_test_id")
            .eq("user_id", uid)
            .eq("status", "completed")
            .order("completed_at", desc=True)
            .limit(200)
            .execute()
        )
    )
    for a in attempts_res.data or []:
        mock_id = str(a.get("mock_test_id") or "")
        if not is_full_mock_id(mock_id):
            continue
        activity_dt = _safe_dt(a.get("completed_at")) or _safe_dt(a.get("started_at"))
        if activity_dt:
            _bump(day_counts, _to_app_date(activity_dt))

    hub_res = execute_with_retry(
        lambda: (
            client.table("user_hub_progress")
            .select("status, completed_at, updated_at")
            .eq("user_id", uid)
            .eq("status", "completed")
            .limit(300)
            .execute()
        )
    )
    for row in hub_res.data or []:
        activity_dt = _safe_dt(row.get("completed_at")) or _safe_dt(row.get("updated_at"))
        if activity_dt:
            _bump(day_counts, _to_app_date(activity_dt))

    try:
        ex_res = execute_with_retry(
            lambda: (
                client.table("practice_exercise_attempts")
                .select("status, completed_at, started_at")
                .eq("user_id", uid)
                .eq("status", "completed")
                .limit(300)
                .execute()
            )
        )
        for row in ex_res.data or []:
            activity_dt = _safe_dt(row.get("completed_at")) or _safe_dt(
                row.get("started_at")
            )
            if activity_dt:
                _bump(day_counts, _to_app_date(activity_dt))
    except Exception:
        pass

    try:
        profile_res = execute_with_retry(
            lambda: (
                client.table("user_learning_profiles")
                .select("study_plan")
                .eq("user_id", uid)
                .limit(1)
                .execute()
            )
        )
        rows = profile_res.data or []
        study_plan = rows[0].get("study_plan") if rows else None
        if isinstance(study_plan, dict):
            for week in study_plan.get("weeks") or []:
                if not isinstance(week, dict):
                    continue
                for day in week.get("days") or []:
                    if not isinstance(day, dict):
                        continue
                    day_s = str(day.get("date") or "")[:10]
                    try:
                        day_d = date.fromisoformat(day_s)
                    except ValueError:
                        continue
                    for task in day.get("tasks") or []:
                        if not isinstance(task, dict):
                            continue
                        if str(task.get("status") or "").lower() in (
                            "done",
                            "completed",
                        ):
                            _bump(day_counts, day_d)
    except Exception:
        pass

    return day_counts


def activity_calendar(
    day_counts: dict[date, int], *, days: int = 84
) -> list[dict[str, Any]]:
    today = datetime.now(APP_TZ).date()
    start = today - timedelta(days=days - 1)
    out: list[dict[str, Any]] = []
    cursor = start
    while cursor <= today:
        out.append({"date": cursor.isoformat(), "count": int(day_counts.get(cursor, 0))})
        cursor += timedelta(days=1)
    return out


def week_active_days(day_counts: dict[date, int]) -> int:
    today = datetime.now(APP_TZ).date()
    monday = today - timedelta(days=today.weekday())
    return sum(
        1 for i in range(7) if day_counts.get(monday + timedelta(days=i), 0) > 0
    )


def _load_attempt_context(user_id: UUID) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    """Load test attempts, mock_tests map, and module_scores for a user."""
    from app.perf.timing import timed_supabase

    client = get_supabase()
    uid = str(user_id)

    attempts_res = timed_supabase(
        "user_activity.test_attempts",
        lambda: execute_with_retry(
            lambda: (
                client.table("test_attempts")
                .select("id, module, status, started_at, completed_at, mock_test_id")
                .eq("user_id", uid)
                .order("started_at", desc=True)
                .limit(100)
                .execute()
            )
        ),
    )
    attempts: list[dict[str, Any]] = list(attempts_res.data or [])

    mock_ids = sorted({a["mock_test_id"] for a in attempts if a.get("mock_test_id")})
    mocks_by_id: dict[str, dict[str, Any]] = {}
    if mock_ids:
        mocks_res = timed_supabase(
            "user_activity.mock_tests",
            lambda: execute_with_retry(
                lambda: (
                    client.table("mock_tests")
                    .select("id, title, catalog_number")
                    .in_("id", mock_ids)
                    .execute()
                )
            ),
        )
        for row in mocks_res.data or []:
            mocks_by_id[str(row["id"])] = row

    attempt_ids = [a["id"] for a in attempts]
    scores_by_attempt: dict[str, dict[str, Any]] = {}
    if attempt_ids:
        scores_res = timed_supabase(
            "user_activity.module_scores",
            lambda: execute_with_retry(
                lambda: (
                    client.table("module_scores")
                    .select("attempt_id, band, raw_score, total_count, module")
                    .in_("attempt_id", attempt_ids)
                    .execute()
                )
            ),
        )
        for row in scores_res.data or []:
            scores_by_attempt[str(row["attempt_id"])] = row

    return attempts, mocks_by_id, scores_by_attempt


def build_user_activity_stats(user_id: UUID) -> dict[str, Any]:
    attempts, mocks_by_id, scores_by_attempt = _load_attempt_context(user_id)

    bands: list[float] = []
    in_progress: list[dict[str, Any]] = []
    recent_modules: list[dict[str, Any]] = []
    last_activity: datetime | None = None
    completed_count = 0

    for a in attempts:
        attempt_started = _safe_dt(a.get("started_at"))
        completed = _safe_dt(a.get("completed_at"))
        latest_dt = completed or attempt_started
        if latest_dt and (last_activity is None or latest_dt > last_activity):
            last_activity = latest_dt

        mock_row = mocks_by_id.get(str(a.get("mock_test_id") or ""))
        mock_id = str(a.get("mock_test_id") or "")
        if not is_full_mock_id(mock_id):
            continue

        module = str(a.get("module") or "")
        status_lc = str(a.get("status") or "").lower()
        mock_title = str(mock_row["title"]) if mock_row else "Untitled mock"
        catalog_number = mock_row.get("catalog_number") if mock_row else None

        if status_lc == "in_progress" and attempt_started:
            in_progress.append(
                {
                    "id": str(a["id"]),
                    "module": module,
                    "started_at": attempt_started,
                    "mock_test_id": mock_id,
                    "mock_title": mock_title,
                    "catalog_number": catalog_number,
                }
            )

        if status_lc == "completed":
            completed_count += 1
            score = scores_by_attempt.get(str(a["id"]))
            band_val = (
                float(score["band"]) if score and score.get("band") is not None else None
            )
            if band_val is not None:
                bands.append(band_val)
            recent_modules.append(
                {
                    "id": str(a["id"]),
                    "module": module,
                    "started_at": attempt_started or datetime.now(UTC),
                    "completed_at": completed,
                    "status": "completed",
                    "band": _round_half(band_val),
                    "raw_score": int(score["raw_score"])
                    if score and score.get("raw_score") is not None
                    else None,
                    "total_count": int(score["total_count"])
                    if score and score.get("total_count") is not None
                    else None,
                    "mock_test_id": mock_id,
                    "mock_title": mock_title,
                    "catalog_number": catalog_number,
                }
            )

    in_progress.sort(key=lambda x: x["started_at"], reverse=True)
    recent_modules.sort(
        key=lambda x: (x.get("completed_at") or x["started_at"]),
        reverse=True,
    )

    avg = sum(bands) / len(bands) if bands else None
    best = max(bands) if bands else None
    day_counts = build_user_activity_day_counts(user_id)
    current_streak, longest_streak = streaks_from_counts(day_counts)

    return {
        "total_attempts": len(attempts),
        "completed_attempts": completed_count,
        "in_progress_attempts": len(in_progress),
        "average_band": _round_half(avg),
        "best_band": _round_half(best),
        "last_activity_at": last_activity,
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "in_progress": in_progress[:10],
        "recent_modules": recent_modules[:25],
    }


def build_user_mock_sessions(user_id: UUID) -> list[dict[str, Any]]:
    client = get_supabase()
    uid = str(user_id)

    mock_rows = execute_with_retry(lambda: (
        client.table("mock_attempts")
        .select(
            "id, mock_test_id, status, started_at, completed_at, mock_tests(title, catalog_number)"
        )
        .eq("user_id", uid)
        .order("started_at", desc=True)
        .limit(50)
        .execute()
    )).data or []

    if not mock_rows:
        return []

    mock_attempt_ids = [UUID(str(r["id"])) for r in mock_rows]
    attempts_by_mock = repo.list_module_attempts_by_mock_ids(mock_attempt_ids)
    completed_ids: list[UUID] = []
    for attempts in attempts_by_mock.values():
        completed_ids.extend(
            UUID(str(a["id"]))
            for a in attempts
            if a.get("status") == "completed"
        )
    scores = repo.list_module_scores_by_attempt_ids(completed_ids)

    sessions: list[dict[str, Any]] = []
    for row in mock_rows:
        mock_attempt_id = UUID(str(row["id"]))
        mock_test_id = UUID(str(row["mock_test_id"]))
        mock_ref = row.get("mock_tests") or {}
        module_attempts = attempts_by_mock.get(str(mock_attempt_id), [])

        listening_band = _module_rollup_band_from_scores(
            module="listening",
            mock_test_id=mock_test_id,
            module_attempts=module_attempts,
            scores_by_attempt=scores,
        )
        reading_band = _module_rollup_band_from_scores(
            module="reading",
            mock_test_id=mock_test_id,
            module_attempts=module_attempts,
            scores_by_attempt=scores,
        )
        writing_band = _module_rollup_band_from_scores(
            module="writing",
            mock_test_id=mock_test_id,
            module_attempts=module_attempts,
            scores_by_attempt=scores,
        )
        speaking_band = _module_rollup_band_from_scores(
            module="speaking",
            mock_test_id=mock_test_id,
            module_attempts=module_attempts,
            scores_by_attempt=scores,
        )
        module_bands = [
            b
            for b in (listening_band, reading_band, writing_band, speaking_band)
            if b is not None
        ]
        aggregate_band = round(sum(module_bands) / len(module_bands), 1) if module_bands else None

        sessions.append(
            {
                "mock_attempt_id": str(mock_attempt_id),
                "mock_test_id": str(mock_test_id),
                "mock_title": mock_ref.get("title"),
                "catalog_number": mock_ref.get("catalog_number"),
                "status": str(row["status"]),
                "started_at": _parse_dt(row["started_at"]),
                "completed_at": (
                    _parse_dt(row["completed_at"]) if row.get("completed_at") else None
                ),
                "listening_band": listening_band,
                "reading_band": reading_band,
                "writing_band": writing_band,
                "speaking_band": speaking_band,
                "aggregate_band": aggregate_band,
            }
        )

    return sessions


def list_user_diagnostics(user_id: UUID) -> list[dict[str, Any]]:
    from postgrest.exceptions import APIError

    client = get_supabase()
    try:
        rows = execute_with_retry(lambda: (
            client.table("diagnostic_attempts")
            .select(
                "id, client_attempt_id, status, listening_band, reading_band, "
                "writing_band, speaking_band, aggregate_band, review, "
                "pack_version, started_at, completed_at"
            )
            .eq("user_id", str(user_id))
            .order("completed_at", desc=True)
            .limit(20)
            .execute()
        )).data or []
    except APIError as exc:
        payload = exc.args[0] if exc.args else {}
        code = payload.get("code") if isinstance(payload, dict) else None
        message = str(payload.get("message", "")) if isinstance(payload, dict) else str(exc)
        if code == "PGRST205" or "diagnostic_attempts" in message:
            return []
        raise

    return [
        {
            "id": str(row["id"]),
            "client_attempt_id": row.get("client_attempt_id"),
            "status": row.get("status"),
            "listening_band": (
                float(row["listening_band"])
                if row.get("listening_band") is not None
                else None
            ),
            "reading_band": (
                float(row["reading_band"])
                if row.get("reading_band") is not None
                else None
            ),
            "writing_band": (
                float(row["writing_band"])
                if row.get("writing_band") is not None
                else None
            ),
            "speaking_band": (
                float(row["speaking_band"])
                if row.get("speaking_band") is not None
                else None
            ),
            "aggregate_band": (
                float(row["aggregate_band"])
                if row.get("aggregate_band") is not None
                else None
            ),
            "review": row.get("review"),
            "pack_version": row.get("pack_version"),
            "started_at": _safe_dt(row.get("started_at")),
            "completed_at": _safe_dt(row.get("completed_at")),
        }
        for row in rows
    ]


def list_user_speaking_reviews(user_id: UUID) -> list[dict[str, Any]]:
    client = get_supabase()
    uid = str(user_id)
    rows = execute_with_retry(lambda: (
        client.table("speaking_reviews")
        .select(
            "id, attempt_id, status, human_band, created_at, "
            "test_attempts!inner(user_id, mock_test_id, mock_tests(title))"
        )
        .eq("test_attempts.user_id", uid)
        .order("created_at", desc=True)
        .limit(25)
        .execute()
    )).data or []

    items: list[dict[str, Any]] = []
    for row in rows:
        attempt = row.get("test_attempts") or {}
        mock_ref = attempt.get("mock_tests") or {}
        items.append(
            {
                "id": str(row["id"]),
                "attempt_id": str(row["attempt_id"]),
                "status": row.get("status"),
                "human_band": (
                    float(row["human_band"])
                    if row.get("human_band") is not None
                    else None
                ),
                "created_at": _parse_dt(row["created_at"]),
                "mock_title": mock_ref.get("title"),
            }
        )
    return items


def batch_user_list_aggregates(user_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Mock counts, completed mocks, last activity, best band per user (list page)."""
    if not user_ids:
        return {}

    client = get_supabase()
    out: dict[str, dict[str, Any]] = {
        uid: {
            "mock_attempt_count": 0,
            "completed_mock_count": 0,
            "last_activity_at": None,
            "best_band": None,
        }
        for uid in user_ids
    }

    mock_rows = execute_with_retry(lambda: (
        client.table("mock_attempts")
        .select("user_id, status, started_at, completed_at")
        .in_("user_id", user_ids)
        .execute()
    )).data or []

    for row in mock_rows:
        uid = str(row["user_id"])
        bucket = out.setdefault(
            uid,
            {
                "mock_attempt_count": 0,
                "completed_mock_count": 0,
                "last_activity_at": None,
                "best_band": None,
            },
        )
        bucket["mock_attempt_count"] += 1
        if str(row.get("status")) == "completed":
            bucket["completed_mock_count"] += 1
        for key in ("started_at", "completed_at"):
            dt = _safe_dt(row.get(key))
            if dt and (
                bucket["last_activity_at"] is None
                or dt > bucket["last_activity_at"]
            ):
                bucket["last_activity_at"] = dt

    attempt_rows = execute_with_retry(lambda: (
        client.table("test_attempts")
        .select("id, user_id, started_at, completed_at")
        .in_("user_id", user_ids)
        .execute()
    )).data or []

    attempt_ids: list[str] = []
    attempt_user: dict[str, str] = {}
    for row in attempt_rows:
        uid = str(row["user_id"])
        aid = str(row["id"])
        attempt_ids.append(aid)
        attempt_user[aid] = uid
        bucket = out.setdefault(
            uid,
            {
                "mock_attempt_count": 0,
                "completed_mock_count": 0,
                "last_activity_at": None,
                "best_band": None,
            },
        )
        for key in ("started_at", "completed_at"):
            dt = _safe_dt(row.get(key))
            if dt and (
                bucket["last_activity_at"] is None
                or dt > bucket["last_activity_at"]
            ):
                bucket["last_activity_at"] = dt

    if attempt_ids:
        score_rows = execute_with_retry(lambda: (
            client.table("module_scores")
            .select("attempt_id, band")
            .in_("attempt_id", attempt_ids)
            .execute()
        )).data or []
        for row in score_rows:
            if row.get("band") is None:
                continue
            uid = attempt_user.get(str(row["attempt_id"]))
            if not uid:
                continue
            band = float(row["band"])
            bucket = out[uid]
            if bucket["best_band"] is None or band > bucket["best_band"]:
                bucket["best_band"] = _round_half(band)

    return out
