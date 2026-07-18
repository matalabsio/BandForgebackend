"""Unit tests for calibration aggregation helpers."""

from __future__ import annotations

from app.writing.calibration import aggregate_calibration, calibrate_fixture, mae
from app.writing.golden import GoldenEssay


def _golden(overall: float = 6.0, **kwargs) -> GoldenEssay:
    return GoldenEssay(
        file="x.txt",
        label="x",
        task_part=2,
        question="Q",
        expected_overall=overall,
        expected_criteria=kwargs.get("criteria"),
        tolerance=kwargs.get("tolerance", 0.5),
        essay="essay",
    )


def test_mae():
    assert mae([0.5, 1.0, 0.0]) == 0.5
    assert mae([]) is None


def test_calibrate_fixture_within_tolerance():
    row = calibrate_fixture(
        _golden(6.0),
        ai_overall=6.5,
        ai_criteria=None,
        json_valid=True,
    )
    assert row.within_tolerance is True
    assert row.delta_overall == 0.5


def test_aggregate_gate_bands():
    g = _golden(6.0)
    ok = calibrate_fixture(g, ai_overall=6.0, ai_criteria=None, json_valid=True)
    bad = calibrate_fixture(g, ai_overall=8.0, ai_criteria=None, json_valid=True)
    gated = aggregate_calibration([ok, bad], gate_bands=True)
    assert gated.passed is False
    ungated = aggregate_calibration([ok, bad], gate_bands=False)
    assert ungated.passed is True
    assert ungated.agreement_rate == 0.5
