"""Self-heal stale learning profiles that ignore a completed diagnostic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.learning.service import _diagnostic_uncounted, ensure_profile


def test_diagnostic_uncounted_false_when_already_counted():
    row = {
        "source_counts": {"diagnostic": 1},
        "module_summary": {},
    }
    assert _diagnostic_uncounted(row, uuid4()) is False


def test_diagnostic_uncounted_false_when_module_bands_present():
    row = {
        "source_counts": {"diagnostic": 0},
        "module_summary": {"listening": {"latest": 6.5}},
    }
    assert _diagnostic_uncounted(row, uuid4()) is False


def test_diagnostic_uncounted_true_when_completed_attempt_exists():
    user_id = uuid4()
    row = {
        "source_counts": {"diagnostic": 0},
        "module_summary": {
            "listening": {"latest": None},
            "reading": {"latest": 0},
            "writing": {},
            "speaking": {},
        },
    }
    mock_sb = MagicMock()
    mock_result = MagicMock()
    mock_result.data = [{"id": "diag-1"}]
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
        mock_result
    )

    with (
        patch("app.learning.service.get_supabase", return_value=mock_sb),
        patch("app.learning.service.execute_with_retry", side_effect=lambda fn: fn()),
    ):
        assert _diagnostic_uncounted(row, user_id) is True


def test_ensure_profile_self_heals_uncounted_diagnostic():
    user_id = uuid4()
    stale = {
        "user_id": str(user_id),
        "source_counts": {"diagnostic": 0},
        "module_summary": {},
        "refreshed_at": "2099-01-01T00:00:00+00:00",
        "plan_week_start": "2099-01-01",
        "study_plan": {},
        "recommendations": [],
        "weekly_goals": [],
        "criterion_trends": {},
        "skill_weaknesses": [],
        "top_weaknesses": [],
        "vocab_stats": {},
        "grammar_stats": {},
    }
    healed = {
        **stale,
        "source_counts": {"diagnostic": 1, "listening": 0, "reading": 0, "writing": 0, "speaking": 0},
        "module_summary": {
            "listening": {"latest": 6.0, "best": 6.0, "n": 1, "gap": None},
            "reading": {"latest": 5.5, "best": 5.5, "n": 1, "gap": None},
            "writing": {"latest": None, "best": None, "n": 0, "gap": None},
            "speaking": {"latest": 5.5, "best": 5.5, "n": 1, "gap": None},
        },
        "current_band": 5.5,
        "target_band": 7.0,
    }

    with (
        patch("app.learning.service.fetch_profile_row", return_value=stale),
        patch("app.learning.service._needs_refresh", return_value=False),
        patch("app.learning.service._diagnostic_uncounted", return_value=True),
        patch("app.learning.service.refresh_profile", return_value=healed) as refresh,
        patch(
            "app.learning.service.row_to_response",
            side_effect=lambda row: row,
        ),
    ):
        result = ensure_profile(user_id)

    refresh.assert_called_once_with(user_id)
    assert result["source_counts"]["diagnostic"] == 1
