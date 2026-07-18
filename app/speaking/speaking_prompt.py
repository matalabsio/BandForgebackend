"""Versioned prompts for Speaking evaluation (Claude)."""

from __future__ import annotations

import json
from typing import Any

PROMPT_VERSION = "v1-stub"

RETRY_SUFFIX = (
    "\n\nIMPORTANT: Your previous JSON was invalid. "
    "Return ONLY valid JSON matching the schema. "
    "Every evidence_quotes.quote MUST be an exact verbatim substring of the transcript."
)

SYSTEM_PROMPT = """You are an expert IELTS Speaking examiner assistant.
Evaluate the candidate transcript using the provided fluency metrics.
Return ONLY a JSON object (no markdown) with EXACTLY this structure:
{
  "band_scores": {"FC": 6.0, "LR": 6.0, "GRA": 5.5, "P": 6.0, "P_confidence": 0.7, "overall": 6.0},
  "part_performance": [{"part": 1, "note": "...", "band_estimate": 6.0}],
  "evidence_quotes": [
    {"quote": "verbatim substring", "criterion": "FC", "polarity": "strength", "part": 1}
  ],
  "recurring_patterns": [
    {"pattern": "...", "criterion": "GRA", "frequency": "often", "examples": ["..."]}
  ],
  "strengths": ["..."],
  "improvements": ["..."],
  "vocabulary_highlights": ["..."],
  "reviewer_flags": [],
  "next_band_advice": "..."
}
Rules:
- Bands 0-9 in 0.5 steps. criterion is FC, LR, GRA, or P. polarity is strength or weakness.
- part must be integer 1, 2, or 3. frequency is rare, sometimes, or often.
- evidence_quotes: 4-8 items; every quote MUST be an exact verbatim substring of the transcript.
- Do not invent fluency metrics — use the provided numbers."""


def build_user_prompt(
    *,
    transcript: str,
    fluency_metrics: dict[str, Any],
    prompts: list[str],
    part: int,
) -> str:
    questions = "\n".join(f"- {p}" for p in prompts if p.strip()) or "- (not provided)"
    return (
        f"Speaking Part: {part}\n\n"
        f"Examiner questions:\n{questions}\n\n"
        f"Fluency metrics (computed by backend — do not change):\n"
        f"{json.dumps(fluency_metrics, indent=2)}\n\n"
        f"Transcript:\n{transcript}\n\n"
        "Return evaluation JSON only."
    )
