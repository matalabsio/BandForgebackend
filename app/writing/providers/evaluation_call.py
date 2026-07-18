"""Shared writing LLM evaluation: JSON parse, coerce, validate, reconcile.

Roadmap mapping:
- Response Parser — parse_json_content / coerce_parsed_evaluation / Pydantic
- Retry Middleware — call_writing_evaluation_with_retry (2 attempts)
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from app.ai_ops.estimator import WritingCallEstimate, estimate_writing_call
from app.diagnostic.evaluation_schemas import EvaluationResponse, reconcile_overall_band
from app.diagnostic.writing_prompt import (
    RETRY_SUFFIX,
    build_user_prompt,
    get_system_prompt,
    resolve_prompt_version,
)
from app.writing.evaluation import min_words_for_part, word_count
from app.writing.providers.constants import WRITING_EVAL_MAX_TOKENS_CLAUDE

logger = logging.getLogger(__name__)

LLMCall = Callable[[str, str], Awaitable[tuple[str, dict[str, Any]]]]


@dataclass(frozen=True)
class WritingEvaluationResult:
    evaluation: EvaluationResponse
    raw_store: dict[str, Any]
    prompt_version: str
    model_name: str
    provider_used: str
    latency_ms: int = 0
    retry_count: int = 0
    estimate: WritingCallEstimate | None = None


def parse_json_content(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("Expected JSON object")
    return parsed


def coerce_parsed_evaluation(
    parsed: dict[str, Any], *, words: int, task_part: int
) -> dict[str, Any]:
    """Ensure LLM JSON has required feedback lists before Pydantic validation."""
    min_words = min_words_for_part(task_part)
    data = dict(parsed)

    if not data.get("strengths"):
        data["strengths"] = (
            ["You attempted to respond to the task."]
            if words > 0
            else ["No substantive response was provided."]
        )
    if not data.get("weaknesses"):
        if words < min_words:
            data["weaknesses"] = [
                f"The response is only {words} words — Task {task_part} requires at least {min_words}.",
            ]
        else:
            data["weaknesses"] = ["The response needs clearer task coverage and development."]
    if not data.get("improvement_tips"):
        data["improvement_tips"] = [
            f"Write a complete answer of at least {min_words} words with an overview, key features, and comparisons.",
        ]
    if "spelling_mistakes" not in data:
        data["spelling_mistakes"] = []
    if "grammar_mistakes" not in data:
        data["grammar_mistakes"] = []
    if data.get("spelling_error_count") is None:
        mistakes = data.get("spelling_mistakes") or []
        data["spelling_error_count"] = len(mistakes) if isinstance(mistakes, list) else 0

    # v5 fields — defaults keep cached v4 payloads valid
    if data.get("next_band_advice") is None:
        data["next_band_advice"] = ""
    elif not isinstance(data.get("next_band_advice"), str):
        data["next_band_advice"] = str(data.get("next_band_advice") or "")

    if data.get("confidence") is None:
        data["confidence"] = 0.5

    if "vocabulary_highlights" not in data or data.get("vocabulary_highlights") is None:
        data["vocabulary_highlights"] = []
    else:
        raw_vocab = data.get("vocabulary_highlights")
        if isinstance(raw_vocab, list):
            normalized = []
            for item in raw_vocab:
                if not isinstance(item, dict):
                    continue
                entry = dict(item)
                pol = str(entry.get("polarity") or "weak").strip().lower()
                entry["polarity"] = "strong" if pol == "strong" else "weak"
                normalized.append(entry)
            data["vocabulary_highlights"] = normalized[:6]

    if "strong_spans" not in data or data.get("strong_spans") is None:
        data["strong_spans"] = []
    elif isinstance(data.get("strong_spans"), list):
        data["strong_spans"] = data["strong_spans"][:4]

    return data


async def call_writing_evaluation_with_retry(
    *,
    llm_call: LLMCall,
    task_part: int,
    question: str,
    essay: str,
    provider_label: str,
    model_name: str,
    provider_used: str,
    visual_description: str | None = None,
    target_band: float | None = None,
) -> WritingEvaluationResult:
    words = word_count(essay)
    user_prompt = build_user_prompt(
        task_part=task_part,
        question=question,
        essay=essay,
        visual_description=visual_description,
        word_count=words,
        target_band=target_band,
    )
    last_error: Exception | None = None
    prompt_ver = resolve_prompt_version()
    system_prompt = get_system_prompt(prompt_ver)
    estimate = estimate_writing_call(
        system=system_prompt,
        user=user_prompt,
        essay_words=words,
    )
    request_meta = {
        "prompt_version": prompt_ver,
        "model": model_name,
        "task_part": task_part,
        "essay_word_count": words,
        "max_tokens": WRITING_EVAL_MAX_TOKENS_CLAUDE,
        "requested_at": datetime.now(UTC).isoformat(),
        "estimated_input_tokens": estimate.input_tokens,
        "estimated_output_tokens": estimate.output_tokens,
        "estimated_cost_usd": estimate.estimated_cost_usd,
        "has_visual_description": bool((visual_description or "").strip()),
        "target_band": target_band,
    }
    t0 = time.perf_counter()
    attempts_used = 0

    for attempt in range(2):
        attempts_used = attempt + 1
        prompt = user_prompt if attempt == 0 else user_prompt + RETRY_SUFFIX
        try:
            content, raw_response = await llm_call(system_prompt, prompt)
            logger.info("%s writing response received (attempt %s)", provider_label, attempt + 1)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            raw_store: dict[str, Any] = {
                "content": content,
                "response": raw_response,
                "provider_used": provider_used,
                "request": {
                    **request_meta,
                    "attempt": attempt + 1,
                    "latency_ms": latency_ms,
                },
            }
            parsed = coerce_parsed_evaluation(
                parse_json_content(content),
                words=words,
                task_part=task_part,
            )
            evaluation = EvaluationResponse.model_validate(parsed)
            ai_overall = evaluation.overall_band
            evaluation, reconciled = reconcile_overall_band(evaluation)
            if reconciled:
                raw_store["overall_band_reconciled"] = True
                raw_store["ai_overall_band"] = ai_overall
                raw_store["calculated_overall_band"] = evaluation.overall_band
                logger.info(
                    "Overall band reconciled: ai=%s calculated=%s",
                    ai_overall,
                    evaluation.overall_band,
                )
            return WritingEvaluationResult(
                evaluation=evaluation,
                raw_store=raw_store,
                prompt_version=prompt_ver,
                model_name=model_name,
                provider_used=provider_used,
                latency_ms=latency_ms,
                retry_count=max(0, attempts_used - 1),
                estimate=estimate,
            )
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            logger.warning(
                "%s writing evaluation validation failed (attempt %s): %s",
                provider_label,
                attempt + 1,
                exc,
            )
        except Exception as exc:
            last_error = exc
            logger.warning(
                "%s writing evaluation call failed (attempt %s): %s",
                provider_label,
                attempt + 1,
                exc,
            )
            break

    raise RuntimeError(
        f"{provider_label} writing evaluation failed: {last_error}"
        if last_error
        else f"{provider_label} writing evaluation failed"
    )
