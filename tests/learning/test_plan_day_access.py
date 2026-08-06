"""Unit tests for sequential plan-day access + update_task_status gating."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.learning.plan_day_access import (
    day_access_denial_detail,
    is_plan_day_accessible,
)
from app.learning.service import update_task_status

USER_ID = UUID("00000000-0000-0000-0000-000000000099")


def _today() -> date:
    return date.today()


def _iso(d: date) -> str:
    return d.isoformat()


def _make_plan(
    *,
    yesterday_done: bool,
    today_done: bool,
    include_day2: bool = True,
) -> dict:
    today = _today()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    day2 = today + timedelta(days=2)
    exam = today + timedelta(days=30)

    days = [
        {
            "date": _iso(yesterday),
            "label": "Y",
            "tasks": [
                {
                    "id": "y1",
                    "title": "Y",
                    "module": "listening",
                    "status": "done" if yesterday_done else "pending",
                }
            ],
        },
        {
            "date": _iso(today),
            "label": "T",
            "tasks": [
                {
                    "id": "today-1",
                    "title": "Today",
                    "module": "listening",
                    "status": "done" if today_done else "pending",
                }
            ],
        },
        {
            "date": _iso(tomorrow),
            "label": "M",
            "tasks": [
                {
                    "id": "tm1",
                    "title": "Tomorrow",
                    "module": "reading",
                    "status": "pending",
                }
            ],
        },
    ]
    if include_day2:
        days.append(
            {
                "date": _iso(day2),
                "label": "D2",
                "tasks": [
                    {
                        "id": "d2",
                        "title": "Day2",
                        "module": "writing",
                        "status": "pending",
                    }
                ],
            }
        )

    return {
        "weekly_focus": "Focus",
        "exam_date": _iso(exam),
        "weeks": [{"id": "w1", "label": "Week 1", "focus": "Focus", "days": days}],
    }


def test_accessible_blocks_tomorrow_when_today_incomplete():
    plan = _make_plan(yesterday_done=True, today_done=False)
    today = _iso(_today())
    tomorrow = _iso(_today() + timedelta(days=1))
    weeks = plan["weeks"]
    assert is_plan_day_accessible(tomorrow, today, plan["exam_date"], weeks) is False
    assert "today" in day_access_denial_detail(
        tomorrow, today, plan["exam_date"], weeks
    ).lower()


def test_accessible_blocks_tomorrow_when_past_incomplete():
    plan = _make_plan(yesterday_done=False, today_done=True)
    today = _iso(_today())
    tomorrow = _iso(_today() + timedelta(days=1))
    weeks = plan["weeks"]
    assert is_plan_day_accessible(tomorrow, today, plan["exam_date"], weeks) is False
    detail = day_access_denial_detail(tomorrow, today, plan["exam_date"], weeks)
    assert "previous" in detail.lower()


def test_accessible_allows_tomorrow_when_prefix_clear():
    plan = _make_plan(yesterday_done=True, today_done=True)
    today = _iso(_today())
    tomorrow = _iso(_today() + timedelta(days=1))
    assert (
        is_plan_day_accessible(tomorrow, today, plan["exam_date"], plan["weeks"])
        is True
    )


def test_accessible_blocks_day_plus_two():
    plan = _make_plan(yesterday_done=True, today_done=True)
    today = _iso(_today())
    day2 = _iso(_today() + timedelta(days=2))
    assert (
        is_plan_day_accessible(day2, today, plan["exam_date"], plan["weeks"]) is False
    )


def _patch_update_deps(plan: dict):
    row = {"study_plan": plan, "exam_date": plan["exam_date"]}
    return (
        patch("app.learning.service.fetch_profile_row", return_value=row),
        patch("app.learning.service.get_supabase", return_value=MagicMock()),
        patch("app.learning.service.execute_with_retry", side_effect=lambda fn: fn()),
        patch("app.learning.service.invalidate_learning_profile_cache"),
    )


def test_update_task_status_rejects_tomorrow_when_backlog():
    plan = _make_plan(yesterday_done=False, today_done=True)
    patches = _patch_update_deps(plan)
    with patches[0], patches[1], patches[2], patches[3]:
        with pytest.raises(HTTPException) as exc:
            update_task_status(USER_ID, "tm1", "done")
        assert exc.value.status_code == 400
        assert "previous" in str(exc.value.detail).lower()


def test_update_task_status_rejects_tomorrow_when_today_incomplete():
    plan = _make_plan(yesterday_done=True, today_done=False)
    patches = _patch_update_deps(plan)
    with patches[0], patches[1], patches[2], patches[3]:
        with pytest.raises(HTTPException) as exc:
            update_task_status(USER_ID, "tm1", "done")
        assert exc.value.status_code == 400
        assert "today" in str(exc.value.detail).lower()


def test_update_task_status_allows_tomorrow_when_clear():
    plan = _make_plan(yesterday_done=True, today_done=True)
    patches = _patch_update_deps(plan)
    with patches[0], patches[1], patches[2], patches[3]:
        result = update_task_status(USER_ID, "tm1", "done")
    assert result.weeks[0].days[2].tasks[0].status == "done"


def test_update_task_status_rejects_day_plus_two():
    plan = _make_plan(yesterday_done=True, today_done=True)
    patches = _patch_update_deps(plan)
    with patches[0], patches[1], patches[2], patches[3]:
        with pytest.raises(HTTPException) as exc:
            update_task_status(USER_ID, "d2", "done")
        assert exc.value.status_code == 400


def test_update_task_status_allows_today_last_task():
    plan = _make_plan(yesterday_done=True, today_done=False)
    patches = _patch_update_deps(plan)
    with patches[0], patches[1], patches[2], patches[3]:
        result = update_task_status(USER_ID, "today-1", "done")
    today_iso = _iso(_today())
    today_day = next(d for w in result.weeks for d in w.days if d.date == today_iso)
    assert today_day.tasks[0].status == "done"
