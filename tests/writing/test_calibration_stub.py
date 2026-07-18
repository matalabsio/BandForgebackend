"""Stub calibration gates JSON validity without requiring gold band match."""

from __future__ import annotations

import asyncio

from app.writing.calibration import aggregate_calibration, calibrate_fixture
from app.writing.golden import load_golden_manifest
from app.writing.providers.factory import evaluate_writing_essay


def test_calibration_stub_json_validity_and_report_shape(monkeypatch):
    monkeypatch.setenv("WRITING_EVAL_STUB", "true")
    from app.config import reload_settings

    reload_settings()

    goldens = load_golden_manifest()[:4]
    rows = []

    async def run_all():
        for golden in goldens:
            result = await evaluate_writing_essay(
                task_part=golden.task_part,
                question=golden.question,
                essay=golden.essay,
            )
            ev = result.evaluation
            rows.append(
                calibrate_fixture(
                    golden,
                    ai_overall=float(ev.overall_band),
                    ai_criteria={
                        "task_achievement": float(ev.task_achievement),
                        "coherence": float(ev.coherence),
                        "lexical_resource": float(ev.lexical_resource),
                        "grammar": float(ev.grammar),
                    },
                    json_valid=True,
                    prompt_version=result.prompt_version,
                    model_name=result.model_name,
                )
            )

    asyncio.run(run_all())
    report = aggregate_calibration(
        rows,
        gate_bands=False,
        prompt_version=rows[0].prompt_version,
        model_name=rows[0].model_name,
    )

    assert report.json_validity_rate == 1.0
    assert report.overall_mae is not None
    assert "task_achievement" in report.criterion_mae
    assert report.passed is True
    assert report.to_dict()["fixtures"]
