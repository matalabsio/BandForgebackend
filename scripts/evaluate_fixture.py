#!/usr/bin/env python3
"""Evaluate curated writing fixtures (stub by default; --live for Claude/Groq).

Usage:
  cd backend && .venv/bin/python scripts/evaluate_fixture.py task2_band6.txt
  cd backend && .venv/bin/python scripts/evaluate_fixture.py --all
  cd backend && .venv/bin/python scripts/evaluate_fixture.py --all --calibrate
  cd backend && .venv/bin/python scripts/evaluate_fixture.py task2_band6.txt --live --calibrate
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings, reload_settings
from app.diagnostic.writing_prompt import resolve_prompt_version
from app.writing.calibration import (
    aggregate_calibration,
    calibrate_fixture,
)
from app.writing.eval_cache import (
    EVALUATION_SOURCE_AI,
    EVALUATION_SOURCE_STUB,
    cache_attempt_id_for_hash,
    lookup_cached_evaluation,
    persist_evaluation,
)
from app.writing.eval_utils import (
    compute_essay_hash,
    count_paragraphs,
    count_sentences,
    sanitize_essay,
    word_count,
    writing_cache_model_key,
)
from app.writing.golden import GoldenEssay, resolve_golden
from app.writing.providers.factory import evaluate_writing_essay, writing_eval_configured


def _hash_for(golden: GoldenEssay) -> str:
    cleaned = sanitize_essay(golden.essay, golden.question)
    return compute_essay_hash(
        task_part=golden.task_part,
        question=golden.question,
        essay=cleaned,
        prompt_version=resolve_prompt_version(),
        model_name=writing_cache_model_key(),
    )


async def _evaluate_entry(
    golden: GoldenEssay,
    *,
    use_cache: bool,
    calibrate: bool,
    gate_bands: bool = True,
) -> tuple[int, Any | None]:
    settings = get_settings()
    cleaned = sanitize_essay(golden.essay, golden.question)
    words = word_count(cleaned)
    essay_hash = _hash_for(golden)
    prompt_ver = resolve_prompt_version()
    model_key = writing_cache_model_key()

    print(f"\n=== {golden.label} ===")
    print(f"  task_part={golden.task_part} words={words} hash={essay_hash[:12]}…")
    print(
        f"  stub={settings.writing_eval_stub} primary={settings.writing_llm_primary} "
        f"prompt={prompt_ver} model_key={model_key}"
    )
    if calibrate:
        print(
            f"  gold overall={golden.expected_overall} tolerance={golden.tolerance}"
        )

    evaluation = None
    result = None
    error: str | None = None
    json_valid = False
    code = 0

    if use_cache:
        cached = lookup_cached_evaluation(essay_hash)
        if cached and not calibrate:
            print(
                f"OK    cache hit id={cached.get('id')} "
                f"band={cached.get('overall_band')} source={cached.get('evaluation_source')}"
            )
            return 0, None

    if not writing_eval_configured():
        msg = "no writing evaluator configured (enable stub or LLM keys)"
        print(f"FAIL  {msg}")
        if calibrate:
            row = calibrate_fixture(
                golden,
                ai_overall=None,
                ai_criteria=None,
                json_valid=False,
                error=msg,
                prompt_version=prompt_ver,
                model_name=model_key,
            )
            return 1, row
        return 1, None

    try:
        result = await evaluate_writing_essay(
            task_part=golden.task_part,
            question=golden.question,
            essay=cleaned,
        )
        evaluation = result.evaluation
        json_valid = True
    except Exception as exc:
        error = str(exc)
        print(f"FAIL  evaluation error: {exc}")
        code = 1

    if evaluation is not None and result is not None:
        evaluation_source = (
            EVALUATION_SOURCE_STUB
            if settings.writing_eval_stub
            else EVALUATION_SOURCE_AI
        )
        if use_cache:
            try:
                persist_evaluation(
                    client_attempt_id=cache_attempt_id_for_hash(essay_hash),
                    essay_hash=essay_hash,
                    task_part=golden.task_part,
                    question=golden.question,
                    original_essay=golden.essay,
                    cleaned_essay=cleaned,
                    evaluation=evaluation,
                    words=words,
                    sentences=count_sentences(cleaned),
                    paragraphs=count_paragraphs(cleaned),
                    raw_ai_response=result.raw_store,
                    prompt_version=result.prompt_version,
                    model_name=result.model_name,
                    evaluation_source=evaluation_source,
                )
            except Exception as exc:
                print(f"WARN  cache persist failed: {exc}")

        print(
            f"OK    provider={result.provider_used} model={result.model_name} "
            f"band={evaluation.overall_band} confidence={evaluation.confidence:.2f} "
            f"prompt={result.prompt_version}"
        )
        print(
            f"      TA={evaluation.task_achievement} CC={evaluation.coherence} "
            f"LR={evaluation.lexical_resource} GRA={evaluation.grammar}"
        )
        if evaluation.next_band_advice:
            print(f"      next-band: {evaluation.next_band_advice}")

    if not calibrate:
        return code, None

    ai_criteria = None
    ai_overall = None
    if evaluation is not None:
        ai_overall = float(evaluation.overall_band)
        ai_criteria = {
            "task_achievement": float(evaluation.task_achievement),
            "coherence": float(evaluation.coherence),
            "lexical_resource": float(evaluation.lexical_resource),
            "grammar": float(evaluation.grammar),
        }

    row = calibrate_fixture(
        golden,
        ai_overall=ai_overall,
        ai_criteria=ai_criteria,
        json_valid=json_valid,
        error=error,
        prompt_version=result.prompt_version if result else prompt_ver,
        model_name=result.model_name if result else model_key,
    )
    if not row.json_valid:
        status = "FAIL"
    elif row.within_tolerance:
        status = "PASS"
    elif gate_bands:
        status = "MISS"
    else:
        # Stub (or ungated) runs: band vs gold is informational only
        status = "INFO"
    note = ""
    if status == "INFO":
        note = " (stub always ~6.0; band gates off)"
    print(
        f"  calib {status}{note} Δ={row.delta_overall} "
        f"within={row.within_tolerance} json_valid={row.json_valid}"
    )
    return code, row


async def _run(
    entries: list[GoldenEssay],
    *,
    use_cache: bool,
    calibrate: bool,
    gate_bands: bool,
    json_report: Path | None,
) -> int:
    if calibrate and not gate_bands:
        print(
            "\nNote: WRITING_EVAL_STUB=true — band MISS vs gold is expected "
            "(stub always returns ~6.0). Only JSON validity gates exit code.\n"
            "For real gold checks: set WRITING_EVAL_STUB=false and run with --live."
        )
    code = 0
    rows = []
    for entry in entries:
        entry_code, row = await _evaluate_entry(
            entry,
            use_cache=use_cache,
            calibrate=calibrate,
            gate_bands=gate_bands,
        )
        code = max(code, entry_code)
        if row is not None:
            rows.append(row)

    if calibrate and rows:
        settings = get_settings()
        report = aggregate_calibration(
            rows,
            gate_bands=gate_bands,
            prompt_version=resolve_prompt_version(),
            model_name=writing_cache_model_key(),
        )
        print("\n=== Calibration summary ===")
        print(f"  fixtures={len(rows)} json_validity={report.json_validity_rate}")
        print(
            f"  overall_mae={report.overall_mae} agreement={report.agreement_rate} "
            f"band_consistency={report.band_consistency}"
        )
        print(f"  criterion_mae={report.criterion_mae}")
        print(
            f"  prompt={report.prompt_version} model={report.model_name} "
            f"gate_bands={report.gate_bands} passed={report.passed} "
            f"stub={settings.writing_eval_stub}"
        )
        if not gate_bands:
            print(
                "  (band agreement is informational in stub mode; "
                "passed requires JSON-valid only)"
            )
        if json_report is not None:
            json_report.write_text(
                json.dumps(report.to_dict(), indent=2),
                encoding="utf-8",
            )
            print(f"  wrote report {json_report}")
        if not report.passed:
            code = max(code, 1)

    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate curated writing fixtures")
    parser.add_argument(
        "fixture",
        nargs="?",
        help="Fixture filename or label (e.g. task2_band6.txt)",
    )
    parser.add_argument("--all", action="store_true", help="Run all manifest fixtures")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Require live LLM (refuses if WRITING_EVAL_STUB=true)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip shared essay_hash cache lookup/persist",
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Compare AI scores to golden expected bands; emit metrics",
    )
    parser.add_argument(
        "--prompt-version",
        default=None,
        help="Force WRITING_PROMPT_VERSION for this run (e.g. v4 or v5)",
    )
    parser.add_argument(
        "--json-report",
        type=Path,
        default=None,
        help="Write calibration JSON report to this path",
    )
    parser.add_argument(
        "--force-band-gates",
        action="store_true",
        help="Fail on band tolerance even in stub mode (default: stub only gates JSON)",
    )
    parser.add_argument("--reload-env", action="store_true")
    args = parser.parse_args()

    if args.prompt_version:
        os.environ["WRITING_PROMPT_VERSION"] = args.prompt_version
        reload_settings()
    elif args.reload_env:
        reload_settings()

    settings = get_settings()
    if args.live and settings.writing_eval_stub:
        print(
            "FAIL  --live requires WRITING_EVAL_STUB=false "
            "(and WRITING_LLM_PRIMARY=claude or groq)"
        )
        return 1
    if args.live and not writing_eval_configured():
        print("FAIL  --live but no writing LLM configured")
        return 1

    try:
        entries = resolve_golden(args.fixture, all_fixtures=args.all)
    except ValueError as exc:
        print(f"FAIL  {exc}")
        return 1

    gate_bands = (not settings.writing_eval_stub) or args.force_band_gates
    return asyncio.run(
        _run(
            entries,
            use_cache=not args.no_cache,
            calibrate=args.calibrate,
            gate_bands=gate_bands if args.calibrate else False,
            json_report=args.json_report,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
