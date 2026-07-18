"""Unit tests for personalized plan sequencing (Phase 1)."""

from __future__ import annotations

from app.learning.plan_sequencing import (
    allocate_days,
    build_session_sequence,
    gap_map,
    is_foundation_path,
    skill_gap,
)


def test_mixed_path_l7_r7_w6_s6():
    bands = {"listening": 7.0, "reading": 7.0, "writing": 6.0, "speaking": 6.0}
    kind, order = build_session_sequence(bands, 7.0)
    assert kind == "mixed"
    assert order == ["writing", "listening", "speaking", "writing", "reading"]


def test_foundation_path_l4_r4_w2_s2():
    bands = {"listening": 4.0, "reading": 4.0, "writing": 2.0, "speaking": 2.0}
    assert is_foundation_path(bands)
    kind, order = build_session_sequence(bands, 7.0)
    assert kind == "foundation"
    assert order == ["listening", "reading", "writing", "speaking"]


def test_hamilton_sums_to_n_l4_r4_w2_s2():
    bands = {"listening": 4.0, "reading": 4.0, "writing": 2.0, "speaking": 2.0}
    gaps = gap_map(bands, 7.0, use_floor=True)
    alloc = allocate_days(gaps, 14)
    assert sum(alloc.values()) == 14
    assert alloc["writing"] == 4
    assert alloc["speaking"] == 4


def test_skill_gap_floor():
    assert skill_gap(7.0, 7.0) == 0.5
    assert skill_gap(None, 7.0) == 7.0
