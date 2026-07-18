"""Tests for personalized study plan builder (Phase 1)."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from app.learning.plan_sequencing import build_session_sequence
from app.learning.rules import build_personalized_study_plan
from app.learning.service import _personalized_plan_is_bloated


def test_build_personalized_study_plan_day_count_and_tasks():
    today = date.today()
    exam = today + timedelta(days=14)
    bands = {"listening": 7.0, "reading": 7.0, "writing": 6.0, "speaking": 6.0}
    plan = build_personalized_study_plan(
        bands=bands,
        target=7.0,
        exam_date=exam,
        prep_start=today,
    )
    assert plan.total_days == 15
    assert plan.prep_start == today
    assert plan.exam_date == exam
    assert plan.plan_tier == "full_skill_program"
    assert plan.session_path_kind == "mixed"

    all_days = [day for week in plan.weeks for day in week.days]
    assert len(all_days) == 15

    today_day = next(d for d in all_days if d.date == today.isoformat())
    task_types = {t.task_type for t in today_day.tasks}
    assert "watch" in task_types
    assert "practice" in task_types
    assert "submit" in task_types


def test_mixed_path_dedupes_repeated_session_skills():
    """Mixed H-E-H-H-E may repeat skills; day tasks keep one stack per unique skill."""
    today = date.today()
    exam = today + timedelta(days=7)
    bands = {"listening": 7.0, "reading": 7.0, "writing": 6.0, "speaking": 6.0}
    path_kind, session_order = build_session_sequence(bands, 7.0)
    assert path_kind == "mixed"
    assert len(session_order) == 5
    assert len(session_order) > len(set(session_order))

    plan = build_personalized_study_plan(
        bands=bands,
        target=7.0,
        exam_date=exam,
        prep_start=today,
    )
    day = plan.weeks[0].days[0]
    watches = [t for t in day.tasks if t.task_type == "watch"]
    watch_by_module = Counter(t.module for t in watches)
    assert all(count == 1 for count in watch_by_module.values())
    assert set(watch_by_module) == set(session_order)

    unique = list(dict.fromkeys(session_order))
    for skill in unique:
        types = {t.task_type for t in day.tasks if t.module == skill}
        assert "watch" in types and "practice" in types
        if skill in ("writing", "speaking"):
            assert "submit" in types


def test_build_personalized_study_plan_foundation_session_order():
    today = date.today()
    exam = today + timedelta(days=6)
    bands = {"listening": 4.0, "reading": 4.0, "writing": 2.0, "speaking": 2.0}
    plan = build_personalized_study_plan(
        bands=bands,
        target=7.0,
        exam_date=exam,
        prep_start=today,
    )
    assert plan.session_path_kind == "foundation"
    first_day = plan.weeks[0].days[0]
    titles = [t.title for t in first_day.tasks]
    assert titles[0] == "Listening — Watch"
    assert titles[1] == "Listening — Practice"
    assert titles[2] == "Reading — Watch"

    watches = [t for t in first_day.tasks if t.task_type == "watch"]
    assert [t.module for t in watches] == [
        "listening",
        "reading",
        "writing",
        "speaking",
    ]
    assert len(watches) == 4


def test_personalized_plan_bloated_detector():
    lean = {
        "weeks": [
            {
                "days": [
                    {
                        "tasks": [
                            {"task_type": "watch", "module": "writing"},
                            {"task_type": "practice", "module": "writing"},
                            {"task_type": "watch", "module": "listening"},
                        ]
                    }
                ]
            }
        ]
    }
    bloated = {
        "weeks": [
            {
                "days": [
                    {
                        "tasks": [
                            {"task_type": "watch", "module": "writing"},
                            {"task_type": "watch", "module": "writing"},
                        ]
                    }
                ]
            }
        ]
    }
    assert _personalized_plan_is_bloated(lean) is False
    assert _personalized_plan_is_bloated(bloated) is True


def test_build_personalized_study_plan_preserves_task_status():
    today = date.today()
    exam = today + timedelta(days=2)
    bands = {"listening": 4.0, "reading": 4.0, "writing": 2.0, "speaking": 2.0}
    prior = build_personalized_study_plan(
        bands=bands,
        target=7.0,
        exam_date=exam,
        prep_start=today,
    ).model_dump(mode="json")
    task_id = prior["weeks"][0]["days"][0]["tasks"][0]["id"]
    prior["weeks"][0]["days"][0]["tasks"][0]["status"] = "done"

    rebuilt = build_personalized_study_plan(
        bands=bands,
        target=7.0,
        exam_date=exam,
        prep_start=today,
        prior_plan=prior,
    )
    first_task = rebuilt.weeks[0].days[0].tasks[0]
    assert first_task.id == task_id
    assert first_task.status == "done"
