"""Service helpers for learning profiles (merge status without DB upsert)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID

from app.learning.schemas import StudyDay, StudyPlan, StudyTask, StudyWeek
from app.learning.service import (
    _serve_rewritten_study_plan,
    _todays_tasks,
    row_to_response,
    sync_study_plan_tasks_for_hub,
    weekly_hub_completions_for_user,
)

USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def test_todays_tasks_filters_current_day():
    today = date.today().isoformat()
    plan = {
        "weekly_focus": "Focus",
        "weeks": [
            {
                "id": "w1",
                "label": "Week 1",
                "focus": "Focus",
                "days": [
                    {
                        "date": today,
                        "label": "Mon",
                        "tasks": [
                            {
                                "id": "t1",
                                "title": "Practice",
                                "subtitle": "",
                                "module": "listening",
                                "kind": "practice",
                                "duration_min": 20,
                                "href": "/mocks",
                                "status": "pending",
                            }
                        ],
                    }
                ],
            }
        ],
    }
    tasks = _todays_tasks(plan)
    assert len(tasks) == 1
    assert tasks[0].id == "t1"


def test_serve_rewritten_plan_updates_hubs_for_today():
    today = date.today()
    plan = {
        "weekly_focus": "Focus",
        "prep_start": today.isoformat(),
        "weeks": [
            {
                "id": "w1",
                "label": "Week 1",
                "focus": "Focus",
                "days": [
                    {
                        "date": today.isoformat(),
                        "label": "Mon",
                        "tasks": [
                            {
                                "id": "watch-l",
                                "title": "Watch",
                                "module": "listening",
                                "task_type": "watch",
                                "hub_id": "old-locked-hub",
                                "href": "/practice/listening/old-locked-hub",
                                "status": "pending",
                            },
                            {
                                "id": "practice-l",
                                "title": "Practice",
                                "module": "listening",
                                "task_type": "practice",
                                "hub_id": "old-locked-hub",
                                "href": "/practice/listening/old-locked-hub",
                                "status": "pending",
                            },
                        ],
                    }
                ],
            }
        ],
    }
    with (
        patch(
            "app.practice.catalog.get_ordered_question_bank_ids_by_skill",
            return_value={
                "listening": ["current-hub", "l2"],
                "reading": [],
                "writing": [],
                "speaking": [],
            },
        ),
        patch(
            "app.practice.catalog.get_hub_set_ids",
            return_value={"old-locked-hub": "set-old", "current-hub": "set-cur", "l2": "set-l2"},
        ),
        patch(
            "app.practice.assignment_ledger.list_user_assignment_ids",
            return_value=(set(), set()),
        ),
        patch("app.practice.repository.get_practice_catalog_version", return_value=1),
        patch("app.cache.hybrid_cache.get_json", return_value=None),
        patch("app.practice.catalog.get_hub_submit_configs_by_id", return_value={}),
    ):
        rewritten = _serve_rewritten_study_plan(
            plan,
            user_id=USER_ID,
            prep_start=today,
            progress_map={},
        )
        tasks = _todays_tasks(rewritten)

    assert len(tasks) == 2
    assert tasks[0].hub_id == "old-locked-hub"
    assert tasks[0].href == (
        "/practice/listening/old-locked-hub?from=plan&task=watch&taskId=watch-l"
    )
    assert tasks[1].href == (
        "/test/1/listening?part=1&auto=1&skill_context=listening"
        "&from=plan&task=practice&hubId=old-locked-hub&taskId=practice-l"
    )


def test_serve_rewritten_plan_unavailable_when_empty_pool():
    today = date.today()
    plan = {
        "weekly_focus": "Focus",
        "prep_start": today.isoformat(),
        "weeks": [
            {
                "id": "w1",
                "label": "Week 1",
                "focus": "Focus",
                "days": [
                    {
                        "date": today.isoformat(),
                        "label": "Mon",
                        "tasks": [
                            {
                                "id": "watch-w",
                                "title": "Watch",
                                "module": "writing",
                                "task_type": "watch",
                                "hub_id": None,
                                "href": "/practice/writing/gone",
                                "status": "pending",
                            }
                        ],
                    }
                ],
            }
        ],
    }
    with (
        patch(
            "app.practice.catalog.get_ordered_question_bank_ids_by_skill",
            return_value={
                "listening": [],
                "reading": [],
                "writing": [],
                "speaking": [],
            },
        ),
        patch("app.practice.catalog.get_hub_set_ids", return_value={}),
        patch(
            "app.practice.assignment_ledger.list_user_assignment_ids",
            return_value=(set(), set()),
        ),
        patch("app.practice.repository.get_practice_catalog_version", return_value=1),
        patch("app.cache.hybrid_cache.get_json", return_value=None),
        patch("app.practice.catalog.get_hub_submit_configs_by_id", return_value={}),
    ):
        rewritten = _serve_rewritten_study_plan(
            plan,
            user_id=USER_ID,
            prep_start=today,
            progress_map={},
        )
        tasks = _todays_tasks(rewritten)

    assert tasks[0].hub_id is None
    assert "unavailable=1" in tasks[0].href
    assert not tasks[0].href.startswith("/practice/writing")


def test_row_to_response_empty_bootstrap():
    row = {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "current_band": None,
        "target_band": 7.0,
        "module_summary": {},
        "criterion_trends": {},
        "skill_weaknesses": [],
        "top_weaknesses": [],
        "vocab_stats": {},
        "grammar_stats": {},
        "recommendations": [
            {
                "id": "onboard-listening",
                "title": "Take a listening practice set",
                "reason": "empty",
                "href": "/mocks",
                "module": "listening",
            }
        ],
        "study_plan": StudyPlan(
            weekly_focus="Start here",
            weeks=[
                StudyWeek(
                    id="w1",
                    label="Week 1",
                    days=[
                        StudyDay(
                            date=date.today().isoformat(),
                            label="Today",
                            tasks=[
                                StudyTask(
                                    id="t-a",
                                    title="First practice",
                                    module="listening",
                                )
                            ],
                        )
                    ],
                )
            ],
        ).model_dump(),
        "weekly_goals": [],
        "source_counts": {},
        "refreshed_at": None,
        "plan_week_start": date.today().isoformat(),
    }
    with patch("app.learning.service._hub_progress_for_user", return_value={}):
        with (
            patch(
                "app.learning.service._serve_rewritten_study_plan",
                side_effect=lambda plan, **_kw: plan,
            ),
            patch(
                "app.practice.service.practice_profile_bundle",
                side_effect=Exception("skip"),
            ),
        ):
            profile = row_to_response(row)
    assert profile.user_id.endswith("0001")
    assert profile.target_band == 7.0
    assert profile.recommendations[0].id == "onboard-listening"
    assert len(profile.todays_tasks) == 1


def test_sync_study_plan_tasks_for_hub_marks_matching_tasks_done():
    row = {
        "study_plan": {
            "weekly_focus": "Writing",
            "weeks": [
                {
                    "id": "w1",
                    "label": "Week 1",
                    "days": [
                        {
                            "date": date.today().isoformat(),
                            "label": "Today",
                            "tasks": [
                                {
                                    "id": "practice-w",
                                    "title": "Practice",
                                    "module": "writing",
                                    "task_type": "practice",
                                    "hub_id": "hub-1",
                                    "status": "pending",
                                },
                                {
                                    "id": "watch-w",
                                    "title": "Watch",
                                    "module": "writing",
                                    "task_type": "watch",
                                    "hub_id": "hub-1",
                                    "status": "pending",
                                },
                            ],
                        }
                    ],
                }
            ],
        }
    }
    updated_payload: dict = {}

    def _capture_update(payload):
        updated_payload.update(payload)
        result = MagicMock()
        result.execute.return_value = MagicMock(data=[{}])
        return result

    table = MagicMock()
    table.update.side_effect = _capture_update
    table.eq.return_value = table
    client = MagicMock()
    client.table.return_value = table

    with (
        patch("app.learning.service.fetch_profile_row", return_value=row),
        patch("app.learning.service.get_supabase", return_value=client),
        patch("app.learning.service.execute_with_retry", side_effect=lambda fn: fn()),
        patch("app.learning.service.invalidate_learning_profile_cache"),
    ):
        changed = sync_study_plan_tasks_for_hub(USER_ID, "hub-1")

    assert changed is True
    tasks = updated_payload["study_plan"]["weeks"][0]["days"][0]["tasks"]
    assert tasks[0]["status"] == "done"
    assert tasks[1]["status"] == "pending"


def test_weekly_hub_completions_for_user_filters_current_week():
    today = date.today()
    week_start = today - __import__("datetime").timedelta(days=today.weekday())
    progress_map = {
        "hub-1": {
            "status": "completed",
            "completed_at": datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc).isoformat(),
        },
        "hub-old": {
            "status": "completed",
            "completed_at": "2020-01-01T00:00:00+00:00",
        },
    }
    hubs_by_skill = {
        "writing": [
            {
                "id": "hub-1",
                "set_id": "set-1",
                "practice_sets": {
                    "id": "set-1",
                    "practice_banks": {"skill": "writing"},
                },
            }
        ]
    }
    rows = weekly_hub_completions_for_user(
        USER_ID,
        progress_map=progress_map,
        hubs_by_skill=hubs_by_skill,
    )
    assert len(rows) == 1
    assert rows[0].hub_id == "hub-1"
    assert rows[0].skill == "writing"
    assert rows[0].date == today.isoformat()
    assert week_start <= date.fromisoformat(rows[0].date) <= week_start + __import__("datetime").timedelta(days=6)
