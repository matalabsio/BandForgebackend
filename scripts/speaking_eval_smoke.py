#!/usr/bin/env python3
"""Smoke-check speaking Phase C evaluator (stub + optional live APIs)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings, reload_settings
from app.speaking.providers.constants import PROVIDER_VERSION
from app.speaking.providers.factory import (
    asr_configured,
    eval_configured,
    get_asr_provider,
    get_eval_provider,
    get_eval_provider_chain,
)

REVIEW_ID = UUID("11111111-1111-4111-8111-111111111111")
ATTEMPT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
MOCK_TEST_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_AUDIO = REPO_ROOT / "test/MT1/LT/audio/Listening_S1_Audio.mp3"

SAMPLE_TRANSCRIPT = (
    "I come from a small city and I really enjoy living there because "
    "it is peaceful and the people are friendly."
)
SAMPLE_METRICS = {
    "words_per_minute": 118,
    "total_speaking_seconds": 42,
    "long_pauses": 1,
    "response_count": 1,
    "questions_asked": 1,
}


def _stub_smoke() -> bool:
    from app.speaking.speaking_evaluator import process_speaking_review

    review_row = {
        "id": str(REVIEW_ID),
        "attempt_id": str(ATTEMPT_ID),
        "audio_url": "speaking/smoke/part-1/recording.webm",
        "submission_meta": {"part": 1, "duration_sec": 30},
        "ai_scores": {"status": "pending"},
        "transcript": None,
    }

    with patch("app.speaking.speaking_evaluator.get_settings") as mock_settings, patch(
        "app.speaking.speaking_evaluator.repo.get_speaking_review_by_id",
        return_value=review_row,
    ), patch(
        "app.speaking.speaking_evaluator.repo.get_attempt",
        return_value={"id": str(ATTEMPT_ID), "mock_test_id": str(MOCK_TEST_ID)},
    ), patch(
        "app.speaking.speaking_evaluator.repo.list_questions_for_part",
        return_value=[{"prompt": "Where are you from?"}],
    ), patch(
        "app.speaking.speaking_evaluator.repo.update_speaking_review_evaluation"
    ) as update_eval:
        settings = mock_settings.return_value
        settings.speaking_eval_stub = True

        process_speaking_review(REVIEW_ID)

        if not update_eval.called:
            print("FAIL  stub pipeline did not persist evaluation")
            return False

        ai_scores = update_eval.call_args.kwargs["ai_scores"]
        if ai_scores.get("status") != "ai_stub":
            print(f"FAIL  expected ai_stub, got {ai_scores.get('status')}")
            return False
        if ai_scores.get("provider_version") != PROVIDER_VERSION:
            print("FAIL  stub missing provider_version")
            return False

    print("OK    stub evaluation pipeline")
    return True


async def _live_asr_smoke() -> bool:
    if not SAMPLE_AUDIO.is_file():
        print(f"FAIL  sample audio not found: {SAMPLE_AUDIO}")
        return False

    asr = get_asr_provider()
    audio_bytes = SAMPLE_AUDIO.read_bytes()

    try:
        result = await asr.transcribe(
            audio_bytes=audio_bytes,
            filename=SAMPLE_AUDIO.name,
        )
    except Exception as exc:
        print(f"FAIL  ASR live call ({asr.name}) — {exc}")
        return False

    if not result.get("text"):
        print("FAIL  ASR returned empty transcript")
        return False

    word_count = len(result.get("words") or [])
    print(f"OK    ASR live {asr.name}/{asr.model} ({word_count} word timestamps)")
    return True


async def _live_eval_smoke() -> bool:
    providers = get_eval_provider_chain()
    if not providers:
        print("FAIL  no configured speaking evaluation providers")
        return False

    last_exc: Exception | None = None
    for eval_provider in providers:
        try:
            evaluation = await eval_provider.evaluate(
                transcript=SAMPLE_TRANSCRIPT,
                fluency_metrics=SAMPLE_METRICS,
                prompts=["Where are you from?"],
                part=1,
            )
        except Exception as exc:
            last_exc = exc
            print(
                f"WARN  eval live call ({eval_provider.name}) failed — trying fallback: {exc}"
            )
            continue

        overall = evaluation.band_scores.overall
        print(
            f"OK    eval live {eval_provider.name}/{eval_provider.model} "
            f"(overall band {overall})"
        )
        return True

    print(f"FAIL  all eval providers failed — last error: {last_exc}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live-asr",
        action="store_true",
        help="Call configured ASR provider with sample MP3",
    )
    parser.add_argument(
        "--live-eval",
        action="store_true",
        help="Call configured evaluation provider with sample transcript",
    )
    args = parser.parse_args()

    reload_settings()
    settings = get_settings()

    asr = get_asr_provider()
    eval_provider = get_eval_provider()

    print("Speaking Phase C smoke")
    print(f"  SPEAKING_EVAL_STUB={settings.speaking_eval_stub}")
    print(f"  ASR_PROVIDER={settings.asr_provider} ({asr.name}, configured={asr_configured()})")
    print(
        f"  LLM_PROVIDER={settings.llm_provider} "
        f"SPEAKING_LLM_FALLBACK={settings.speaking_llm_fallback} "
        f"(configured={eval_configured()})"
    )

    if not _stub_smoke():
        return 1

    if args.live_asr:
        if not asr_configured():
            print("SKIP  --live-asr requires configured ASR provider API key")
            return 1
        if not asyncio.run(_live_asr_smoke()):
            return 1

    if args.live_eval:
        if not eval_configured():
            print("SKIP  --live-eval requires configured evaluation provider API key")
            return 1
        if not asyncio.run(_live_eval_smoke()):
            return 1

    print("\nSpeaking evaluator smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
