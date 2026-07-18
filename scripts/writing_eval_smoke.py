#!/usr/bin/env python3
"""Smoke-check writing evaluation (stub by default; optional --live)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings, reload_settings
from app.speaking.claude_client import claude_configured, resolve_claude_auth_mode
from app.writing.providers.constants import PROVIDER_NAME_STUB
from app.writing.providers.factory import evaluate_writing_essay, writing_eval_configured

SAMPLE_QUESTION = (
    "Some people believe that technology has made our lives more complicated. "
    "Others think it has made life easier. Discuss both views and give your own opinion."
)

SAMPLE_ESSAY = """Technology has transformed modern society in profound ways, and opinions differ on whether this change is beneficial or harmful. On one hand, critics argue that smartphones, social media, and constant connectivity have made daily life more stressful. People feel pressured to respond immediately to messages, and the boundary between work and personal time has blurred.

On the other hand, supporters point to undeniable conveniences. Online banking, telemedicine, and remote work have saved time and expanded opportunities, especially for people in rural areas. Educational resources are now accessible worldwide, allowing students to learn at their own pace. In my view, technology itself is neutral; the key is how we use it. With sensible boundaries and digital literacy, technology can simplify life rather than complicate it."""


async def _stub_smoke(*, task_part: int, question: str, essay: str) -> int:
    with patch("app.writing.providers.factory.get_settings") as settings_factory, patch(
        "app.writing.providers.stub_eval.WRITING_STUB_DELAY_SEC",
        0,
    ):
        settings = settings_factory.return_value
        settings.writing_eval_stub = True
        settings.writing_llm_primary = "none"
        settings.writing_llm_fallback = "none"

        result = await evaluate_writing_essay(
            task_part=task_part,
            question=question,
            essay=essay,
        )

    if result.provider_used != PROVIDER_NAME_STUB:
        print(f"FAIL  expected provider=stub, got {result.provider_used}")
        return 1
    if result.evaluation.overall_band < 0 or result.evaluation.overall_band > 9:
        print("FAIL  stub band out of range")
        return 1
    print(
        f"OK    stub evaluation band={result.evaluation.overall_band} "
        f"provider={result.provider_used}"
    )
    return 0


async def _live_smoke(*, task_part: int, question: str, essay: str) -> int:
    settings = get_settings()
    print(
        f"  WRITING_EVAL_STUB={settings.writing_eval_stub} "
        f"WRITING_LLM_PRIMARY={settings.writing_llm_primary} "
        f"WRITING_LLM_FALLBACK={settings.writing_llm_fallback}"
    )
    print(f"  Claude configured: {claude_configured()} ({resolve_claude_auth_mode()})")
    print(f"  Groq configured: {bool(settings.groq_api_key.strip())}")

    if settings.writing_eval_stub:
        print("FAIL  --live requires WRITING_EVAL_STUB=false")
        return 1

    if not writing_eval_configured():
        print("FAIL  no writing LLM provider configured")
        return 1

    try:
        result = await evaluate_writing_essay(
            task_part=task_part,
            question=question,
            essay=essay,
        )
    except Exception as exc:
        print(f"FAIL  evaluation error: {exc}")
        return 1

    print(f"OK    provider={result.provider_used} model={result.model_name}")
    print(f"      overall_band={result.evaluation.overall_band}")
    print(
        "      criteria="
        f"TA {result.evaluation.task_achievement} "
        f"CC {result.evaluation.coherence} "
        f"LR {result.evaluation.lexical_resource} "
        f"GRA {result.evaluation.grammar}"
    )
    print(f"      spelling_mistakes={len(result.evaluation.spelling_mistakes)}")
    if result.evaluation.spelling_mistakes:
        print(
            "      example_spelling="
            f"{result.evaluation.spelling_mistakes[0].original}"
            f" -> {result.evaluation.spelling_mistakes[0].correction}"
        )
    print(
        "      feedback="
        + json.dumps(
            {
                "strengths": result.evaluation.strengths[:2],
                "weaknesses": result.evaluation.weaknesses[:2],
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Writing evaluation smoke test")
    parser.add_argument("--task-part", type=int, default=2, choices=[1, 2])
    parser.add_argument("--question", default=SAMPLE_QUESTION)
    parser.add_argument("--essay", default=SAMPLE_ESSAY)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call configured live LLM (default: stub smoke)",
    )
    parser.add_argument("--reload-env", action="store_true")
    args = parser.parse_args()

    if args.reload_env:
        reload_settings()

    if args.live:
        return asyncio.run(
            _live_smoke(
                task_part=args.task_part,
                question=args.question,
                essay=args.essay,
            )
        )
    return asyncio.run(
        _stub_smoke(
            task_part=args.task_part,
            question=args.question,
            essay=args.essay,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
