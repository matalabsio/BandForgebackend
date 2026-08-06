"""Sequential study-plan day access (shared policy with frontend calendar)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

PLAN_AHEAD_MAX_DAYS = 1


def add_calendar_days(iso: str, days: int) -> str:
    return (date.fromisoformat(iso) + timedelta(days=days)).isoformat()


def _countable_tasks(day: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for task in day.get("tasks") or []:
        if isinstance(task, dict) and task.get("status") != "skipped":
            out.append(task)
    return out


def is_plan_day_fully_complete(day: dict[str, Any] | None) -> bool:
    if day is None:
        return True
    tasks = _countable_tasks(day)
    if not tasks:
        return True
    return all(t.get("status") == "done" for t in tasks)


def flatten_plan_days(weeks: list[Any]) -> list[dict[str, Any]]:
    days: list[dict[str, Any]] = []
    for week in weeks:
        if not isinstance(week, dict):
            continue
        for day in week.get("days") or []:
            if isinstance(day, dict) and isinstance(day.get("date"), str):
                days.append(day)
    days.sort(key=lambda d: d["date"])
    return days


def find_plan_day(weeks: list[Any], target_date: str) -> dict[str, Any] | None:
    for day in flatten_plan_days(weeks):
        if day.get("date") == target_date:
            return day
    return None


def are_all_prior_plan_days_complete(weeks: list[Any], target_date: str) -> bool:
    for day in flatten_plan_days(weeks):
        day_date = day.get("date")
        if not isinstance(day_date, str) or day_date >= target_date:
            continue
        if not is_plan_day_fully_complete(day):
            return False
    return True


def find_task_day(
    weeks: list[Any], task_id: str
) -> tuple[dict[str, Any] | None, str | None]:
    for day in flatten_plan_days(weeks):
        for task in day.get("tasks") or []:
            if isinstance(task, dict) and str(task.get("id")) == task_id:
                date_val = day.get("date")
                return day, date_val if isinstance(date_val, str) else None
    return None, None


def is_plan_day_accessible(
    day_date: str,
    today: str,
    exam_date: str | None,
    weeks: list[Any],
) -> bool:
    if exam_date and day_date > exam_date:
        return False
    if day_date <= today:
        return True
    if day_date > add_calendar_days(today, PLAN_AHEAD_MAX_DAYS):
        return False
    today_day = find_plan_day(weeks, today)
    if not is_plan_day_fully_complete(today_day):
        return False
    if not are_all_prior_plan_days_complete(weeks, day_date):
        return False
    return True


def day_access_denial_detail(
    day_date: str,
    today: str,
    exam_date: str | None,
    weeks: list[Any],
) -> str:
    """Human-readable reason when a future (or post-exam) day is not accessible."""
    if exam_date and day_date > exam_date:
        return "That plan day is after your exam date."
    if day_date <= today:
        return "That plan day is not available."
    if day_date > add_calendar_days(today, PLAN_AHEAD_MAX_DAYS):
        return "That plan day is not unlocked yet."

    # Past incomplete before today?
    for day in flatten_plan_days(weeks):
        d = day.get("date")
        if not isinstance(d, str) or d >= today:
            continue
        if not is_plan_day_fully_complete(day):
            return "Complete previous plan days before moving ahead."

    today_day = find_plan_day(weeks, today)
    if not is_plan_day_fully_complete(today_day):
        return "Finish today's plan before starting tomorrow's tasks."

    if not are_all_prior_plan_days_complete(weeks, day_date):
        return "Complete previous plan days before moving ahead."

    return "That plan day is not unlocked yet."
