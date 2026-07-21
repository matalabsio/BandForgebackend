"""Shared LLM evaluation retry: JSON parse, Pydantic, quote validation."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from app.speaking.evaluation_schemas import (
    SpeakingEvaluation,
    coerce_speaking_evaluation_payload,
    parse_json_content,
    validate_evidence_against_responses,
    validate_quotes_in_transcript,
)
from app.speaking.speaking_prompt import RETRY_SUFFIX, SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)

LLMCall = Callable[[str, str], Awaitable[tuple[str, dict]]]


async def call_evaluation_with_retry(
    *,
    llm_call: LLMCall,
    transcript: str,
    fluency_metrics: dict,
    prompts: list[str],
    part: int,
    provider_label: str,
    responses: list[dict] | None = None,
) -> SpeakingEvaluation:
    user_prompt = build_user_prompt(
        transcript=transcript,
        fluency_metrics=fluency_metrics,
        prompts=prompts,
        part=part,
        responses=responses,
    )
    last_error: Exception | None = None
    for attempt in range(2):
        suffix = RETRY_SUFFIX if attempt > 0 else ""
        content, _raw = await llm_call(SYSTEM_PROMPT, user_prompt + suffix)
        try:
            parsed = parse_json_content(content)
            parsed = coerce_speaking_evaluation_payload(
                parsed, part=part, transcript=transcript
            )
            evaluation = SpeakingEvaluation.model_validate(parsed)
            if responses:
                validate_evidence_against_responses(evaluation, responses)
            else:
                validate_quotes_in_transcript(evaluation, transcript)
            return evaluation
        except (ValueError, ValidationError) as exc:
            last_error = exc
            logger.warning(
                "%s evaluation validation failed (attempt %s)",
                provider_label,
                attempt + 1,
            )
    raise RuntimeError(
        f"{provider_label} evaluation failed validation: {last_error}"
    )
