"""Structured pre-call AI evaluation logging (no essay body)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.ai_ops.estimator import WritingCallEstimate

logger = logging.getLogger("bandforge.ai_ops")


def log_writing_eval_request(
    *,
    provider: str,
    model: str,
    estimate: WritingCallEstimate,
    skipped_reason: str | None = None,
) -> None:
    ts = datetime.now(UTC).isoformat()
    lines = [
        "========================================",
        "Writing Evaluation",
        "========================================",
        f"Provider: {provider}",
        f"Model: {model}",
        f"Essay words: {estimate.essay_words}",
        f"Estimated input tokens: {estimate.input_tokens}",
        f"Estimated output tokens: {estimate.output_tokens}",
        f"Estimated total tokens: {estimate.total_tokens}",
        f"Estimated cost: ${estimate.estimated_cost_usd:.4f}",
        f"Time: {ts}",
    ]
    if skipped_reason:
        lines.append(f"Skipped: {skipped_reason}")
    lines.append("========================================")
    logger.info("\n".join(lines))


__all__ = ["log_writing_eval_request"]
