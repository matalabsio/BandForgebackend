"""Refresh guard for personalized plans."""

from __future__ import annotations

from datetime import date, timedelta

from app.learning.service import _has_active_personalized_plan, _needs_refresh


def test_has_active_personalized_plan_true_before_exam():
    row = {
        "plan_tier": "full_skill_program",
        "exam_date": (date.today() + timedelta(days=5)).isoformat(),
        "study_plan": {"plan_tier": "full_skill_program"},
    }
    assert _has_active_personalized_plan(row) is True


def test_has_active_personalized_plan_false_after_exam():
    row = {
        "plan_tier": "full_skill_program",
        "exam_date": (date.today() - timedelta(days=1)).isoformat(),
        "study_plan": {},
    }
    assert _has_active_personalized_plan(row) is False


def test_needs_refresh_skips_week_start_for_personalized_plan():
    row = {
        "plan_tier": "full_skill_program",
        "exam_date": (date.today() + timedelta(days=10)).isoformat(),
        "plan_week_start": "2000-01-01",
        "refreshed_at": "2099-01-01T00:00:00+00:00",
        "study_plan": {"plan_tier": "full_skill_program"},
    }
    assert _needs_refresh(row) is False
