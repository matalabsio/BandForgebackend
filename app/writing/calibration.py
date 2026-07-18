"""Writing eval calibration metrics against golden essays."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.writing.golden import CRITERIA_KEYS, GoldenEssay


def _round_half(value: float) -> float:
    return round(value * 2) / 2


def mae(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(abs(v) for v in values) / len(values), 3)


@dataclass
class FixtureCalibrationResult:
    label: str
    file: str
    expected_overall: float
    ai_overall: float | None
    delta_overall: float | None
    within_tolerance: bool
    json_valid: bool
    criterion_deltas: dict[str, float | None] = field(default_factory=dict)
    error: str | None = None
    prompt_version: str | None = None
    model_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CalibrationReport:
    fixtures: list[FixtureCalibrationResult]
    overall_mae: float | None
    agreement_rate: float | None
    band_consistency: float | None
    json_validity_rate: float
    criterion_mae: dict[str, float | None]
    prompt_version: str | None = None
    model_name: str | None = None
    gate_bands: bool = True
    passed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixtures": [f.to_dict() for f in self.fixtures],
            "overall_mae": self.overall_mae,
            "agreement_rate": self.agreement_rate,
            "band_consistency": self.band_consistency,
            "json_validity_rate": self.json_validity_rate,
            "criterion_mae": self.criterion_mae,
            "prompt_version": self.prompt_version,
            "model_name": self.model_name,
            "gate_bands": self.gate_bands,
            "passed": self.passed,
        }


def calibrate_fixture(
    golden: GoldenEssay,
    *,
    ai_overall: float | None,
    ai_criteria: dict[str, float] | None,
    json_valid: bool,
    error: str | None = None,
    prompt_version: str | None = None,
    model_name: str | None = None,
) -> FixtureCalibrationResult:
    delta: float | None = None
    within = False
    if ai_overall is not None and json_valid:
        delta = _round_half(float(ai_overall) - golden.expected_overall)
        within = abs(delta) <= golden.tolerance

    criterion_deltas: dict[str, float | None] = {}
    if golden.expected_criteria and ai_criteria:
        for key in CRITERIA_KEYS:
            expected = golden.expected_criteria.get(key)
            actual = ai_criteria.get(key)
            if expected is None or actual is None:
                criterion_deltas[key] = None
            else:
                criterion_deltas[key] = _round_half(float(actual) - float(expected))
    elif golden.expected_criteria:
        for key in CRITERIA_KEYS:
            criterion_deltas[key] = None

    return FixtureCalibrationResult(
        label=golden.label,
        file=golden.file,
        expected_overall=golden.expected_overall,
        ai_overall=ai_overall,
        delta_overall=delta,
        within_tolerance=within,
        json_valid=json_valid,
        criterion_deltas=criterion_deltas,
        error=error,
        prompt_version=prompt_version,
        model_name=model_name,
    )


def aggregate_calibration(
    results: list[FixtureCalibrationResult],
    *,
    gate_bands: bool = True,
    prompt_version: str | None = None,
    model_name: str | None = None,
) -> CalibrationReport:
    total = len(results)
    json_ok = sum(1 for r in results if r.json_valid)
    scored = [r for r in results if r.json_valid and r.ai_overall is not None]
    agreed = [r for r in scored if r.within_tolerance]
    overall_deltas = [
        abs(r.delta_overall)
        for r in scored
        if r.delta_overall is not None
    ]

    criterion_abs: dict[str, list[float]] = {k: [] for k in CRITERIA_KEYS}
    for r in scored:
        for key, delta in r.criterion_deltas.items():
            if delta is not None and key in criterion_abs:
                criterion_abs[key].append(abs(delta))

    json_rate = round(json_ok / total, 3) if total else 0.0
    agreement = round(len(agreed) / len(scored), 3) if scored else None
    band_consistency = agreement

    passed = json_rate == 1.0 and all(r.error is None for r in results)
    if gate_bands and scored:
        passed = passed and all(r.within_tolerance for r in scored)

    return CalibrationReport(
        fixtures=results,
        overall_mae=mae(overall_deltas),
        agreement_rate=agreement,
        band_consistency=band_consistency,
        json_validity_rate=json_rate,
        criterion_mae={k: mae(v) for k, v in criterion_abs.items()},
        prompt_version=prompt_version,
        model_name=model_name,
        gate_bands=gate_bands,
        passed=passed,
    )


__all__ = [
    "CalibrationReport",
    "FixtureCalibrationResult",
    "aggregate_calibration",
    "calibrate_fixture",
    "mae",
]
