"""Phase 4 reliability metrics smoke tests."""

from __future__ import annotations

from app.reliability.metrics import (
    incr,
    mark_tasks_assigned_once,
    record_event,
    record_latency,
    snapshot,
)


def test_reliability_snapshot_shape():
    incr("task_done")
    record_event("planner_failure", detail="unit-test")
    record_latency("/api/learning/profile", 42.5)
    snap = snapshot()
    assert "counters" in snap
    assert "latency" in snap
    assert snap["counters"]["task_done"] >= 1
    assert snap["counters"]["planner_failure"] >= 1
    assert isinstance(snap["recent_events"], list)
    assert "practice" in snap
    assert "hubs_by_skill" in snap["practice"]
    assert "notifications" in snap
    assert "queued" in snap["notifications"]


def test_mark_tasks_assigned_once_dedupes():
    uid = "00000000-0000-4000-8000-00000000rel1"
    first = mark_tasks_assigned_once(uid, amount=3)
    second = mark_tasks_assigned_once(uid, amount=3)
    assert first is True
    assert second is False
