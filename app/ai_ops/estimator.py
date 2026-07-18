"""Token and cost estimation for AI writing evaluations."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.config import get_settings
from app.writing.providers.constants import WRITING_EVAL_MAX_TOKENS_CLAUDE


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token)."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def estimate_cost_usd(
    *,
    input_tokens: int,
    output_tokens: int,
    input_usd_per_mtok: float | None = None,
    output_usd_per_mtok: float | None = None,
) -> float:
    settings = get_settings()
    in_rate = (
        input_usd_per_mtok
        if input_usd_per_mtok is not None
        else float(settings.ai_input_usd_per_mtok)
    )
    out_rate = (
        output_usd_per_mtok
        if output_usd_per_mtok is not None
        else float(settings.ai_output_usd_per_mtok)
    )
    return (input_tokens / 1_000_000.0) * in_rate + (output_tokens / 1_000_000.0) * out_rate


@dataclass(frozen=True)
class WritingCallEstimate:
    essay_words: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float


def estimate_writing_call(
    *,
    system: str,
    user: str,
    essay_words: int,
    max_output_tokens: int = WRITING_EVAL_MAX_TOKENS_CLAUDE,
) -> WritingCallEstimate:
    input_tokens = estimate_tokens(system) + estimate_tokens(user)
    # Cap expected output below max_tokens for cost display
    output_tokens = min(max_output_tokens, max(400, max_output_tokens // 2))
    cost = estimate_cost_usd(input_tokens=input_tokens, output_tokens=output_tokens)
    return WritingCallEstimate(
        essay_words=essay_words,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        estimated_cost_usd=round(cost, 6),
    )


__all__ = [
    "WritingCallEstimate",
    "estimate_cost_usd",
    "estimate_tokens",
    "estimate_writing_call",
]
