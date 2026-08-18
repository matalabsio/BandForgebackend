"""Service helpers for learning profiles (merge status without DB upsert)."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch
from uuid import UUID

from app.learning.schemas import StudyDay, StudyPlan, StudyTask, StudyWeek
from app.learning.service import (
    _serve_rewritten_study_plan,
    _todays_tasks,
    row_to_response,
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
