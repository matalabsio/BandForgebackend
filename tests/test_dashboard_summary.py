"""Dashboard summary schema extensions."""

from __future__ import annotations

from app.routers.dashboard import (
    DashboardMockSnapshot,
    DashboardStats,
    DashboardSummary,
    RecentAttempt,
    _completed_ai_band,
)


def test_dashboard_summary_includes_mock_snapshot_fields():
    snapshot = DashboardMockSnapshot(
        mock_attempt_id="ma-1",
        mock_test_id="mt-1",
        catalog_number=1,
        status="in_progress",
        listening_band=6.5,
        reading_band=None,
        writing_band=None,
        speaking_band=None,
        aggregate_band=6.5,
    )
    summary = DashboardSummary(
        stats=DashboardStats(),
        completed_mock_count=0,
        latest_mock=snapshot,
    )
    assert summary.completed_mock_count == 0
    assert summary.latest_mock is not None
    assert summary.latest_mock.listening_band == 6.5


def test_completed_mock_count_defaults():
    summary = DashboardSummary(stats=DashboardStats())
    assert summary.completed_mock_count == 0
    assert summary.latest_mock is None


def test_completed_ai_band_only_exposes_finished_valid_evaluation():
    assert (
        _completed_ai_band(
            {
                "evaluation_status": "completed",
                "ai_scores": {"status": "ai_complete", "ai_band": 6.5},
            }
        )
        == 6.5
    )
    assert (
        _completed_ai_band(
            {
                "evaluation_status": "processing",
                "ai_scores": {"status": "ai_processing", "ai_band": 6.5},
            }
        )
        is None
    )
    assert (
        _completed_ai_band(
            {
                "evaluation_status": "completed",
                "ai_scores": {"status": "ai_complete", "ai_band": 6.25},
            }
        )
        is None
    )


def test_recent_attempt_exposes_provisional_score_source():
    attempt = RecentAttempt(
        id="attempt-1",
        module="speaking",
        started_at="2026-07-21T10:00:00Z",
        completed_at="2026-07-21T10:10:00Z",
        status="completed",
        band=6.5,
        score_source="ai_estimate",
        mock_test={"id": "mock-1", "title": "Mock Test 1"},
    )
    assert attempt.band == 6.5
    assert attempt.score_source == "ai_estimate"
