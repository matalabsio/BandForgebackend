"""Service helpers for learning profiles (merge status without DB upsert)."""

from __future__ import annotations

from app.learning.schemas import StudyDay, StudyPlan, StudyTask, StudyWeek
from app.learning.service import _todays_tasks, row_to_response
from datetime import date


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
    profile = row_to_response(row)
    assert profile.user_id.endswith("0001")
    assert profile.target_band == 7.0
    assert profile.recommendations[0].id == "onboard-listening"
    assert len(profile.todays_tasks) == 1
