"""Dashboard summary schema extensions."""

from __future__ import annotations

from app.routers.dashboard import DashboardMockSnapshot, DashboardSummary


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
        completed_mock_count=0,
        latest_mock=snapshot,
    )
    assert summary.completed_mock_count == 0
    assert summary.latest_mock is not None
    assert summary.latest_mock.listening_band == 6.5


def test_completed_mock_count_defaults():
    summary = DashboardSummary()
    assert summary.completed_mock_count == 0
    assert summary.latest_mock is None
