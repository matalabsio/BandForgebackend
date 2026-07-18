"""Timeline fields on learning profile responses."""

from __future__ import annotations

from datetime import date, timedelta

from app.learning.service import _timeline_fields


def test_timeline_fields_current_day_and_days_remaining():
    today = date.today()
    prep = today
    exam = today + timedelta(days=10)
    row = {
        "prep_start": prep.isoformat(),
        "exam_date": exam.isoformat(),
        "total_days": 11,
        "skill_difficulty": {"writing": "hard"},
    }
    timeline = _timeline_fields(row, {}, today=today)
    assert timeline["current_day"] == 1
    assert timeline["days_remaining"] == 10
    assert timeline["skill_difficulty"]["writing"] == "hard"
