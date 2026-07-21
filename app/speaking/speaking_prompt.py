"""Versioned prompts for Speaking evaluation (Claude)."""

from __future__ import annotations

import json
from typing import Any

PROMPT_VERSION = "v4-human-report-alignment"

RETRY_SUFFIX = (
    "\n\nIMPORTANT: Your previous JSON was invalid. "
    "Return ONLY valid JSON matching the schema. "
    "Every evidence quote MUST be an exact verbatim substring of its referenced response."
)

SYSTEM_PROMPT = """You are an expert IELTS Speaking examiner assistant.
Evaluate the candidate transcript using the provided fluency metrics.
Return ONLY a JSON object (no markdown) with EXACTLY this structure:
{
  "band_scores": {"FC": 6.0, "LR": 6.0, "GRA": 5.5, "P": 6.0, "P_confidence": 0.7,
                  "P_inference_source": "transcript_inferred", "P_advisory_only": true,
                  "overall": 6.0},
  "part_performance": [{"part": 1, "note": "...", "band_estimate": 6.0}],
  "evidence_quotes": [
    {"response_id": "uuid", "question_id": "uuid", "part": 1,
     "quote": "verbatim substring", "criterion": "FC", "polarity": "strength",
     "issue": "specific observed issue or strength", "title": "short label",
     "explanation": "why this affects the criterion", "suggestion": "actionable advice"}
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
- Score the complete attempt holistically against IELTS Speaking public band descriptors.
- For a complete attempt containing Parts 1, 2, and 3, part_performance must contain
  exactly one distinct entry for each part. Each note must describe observed behaviour
  in that part: answer development in Part 1, structure and sustained narration in Part 2,
  and abstract idea development under follow-up pressure in Part 3. Never copy the same
  generic note across parts.
- Ground comparisons in supplied metrics. You may describe a measured WPM change, pause
  count, response length, or answer-shortening trend only when the supplied numbers support it.
- Preserve response boundaries. Never combine words from separate responses into one quote.
- evidence_quotes: 4-8 items. response_id, question_id and part must exactly match
  the referenced response; quote must be an exact verbatim substring of that response.
- issue, title, explanation and suggestion are required on every evidence item.
- Include both strengths and weaknesses in evidence_quotes. Prefer a signature Part 2 or
  Part 3 excerpt that clearly demonstrates why a criterion score was awarded.
- recurring_patterns must be genuinely recurring across the supplied transcripts. Every
  example must be an exact transcript substring. Do not manufacture occurrence counts;
  frequency is a qualitative estimate and the server derives grounded counts separately.
- strengths must contain 2-4 specific positive findings. improvements must contain 2-4
  prioritized, actionable changes, naming FC, LR, GRA, or Pronunciation where useful.
- next_band_advice must identify the weakest observed part or criterion, explain the
  evidence behind it, and prescribe one repeatable answer structure or drill. Frame it as
  the clearest next step toward a 0.5-band improvement, not a guaranteed score increase.
- Never claim that fixing one issue will mathematically change the overall band unless the
  released human scores and target calculation supplied by the application establish that.
- You receive transcripts and timing metrics, not acoustic pronunciation evidence.
  Pronunciation is always transcript-inferred and advisory: set P_inference_source to
  "transcript_inferred" and P_advisory_only to true. If P_confidence < 0.7, also add
  "low_confidence_pronunciation" to reviewer_flags. A human examiner listening to the
  recording is the authority for the released pronunciation score.
- Do not invent fluency metrics — use the provided numbers."""


def build_user_prompt(
    *,
    transcript: str,
    fluency_metrics: dict[str, Any],
    prompts: list[str],
    part: int,
    responses: list[dict[str, Any]] | None = None,
) -> str:
    if responses:
        blocks = []
        for response in responses:
            blocks.append(
                json.dumps(
                    {
                        "response_id": response["response_id"],
                        "question_id": response["question_id"],
                        "part": response["part"],
                        "sequence_number": response["sequence_number"],
                        "prompt": response.get("prompt"),
                        "transcript": response.get("transcript"),
                        "fluency_metrics": response.get("fluency_metrics"),
                    },
                    ensure_ascii=False,
                )
            )
        return (
            "Evaluate this complete Speaking attempt in sequence. Each JSON line is an "
            "immutable response boundary.\n\n"
            + "\n".join(blocks)
            + "\n\nAttempt and part metrics (computed by backend — do not change):\n"
            + json.dumps(fluency_metrics, indent=2)
            + "\n\nReturn evaluation JSON only."
        )
    questions = "\n".join(f"- {p}" for p in prompts if p.strip()) or "- (not provided)"
    return (
        f"Speaking Part: {part}\n\n"
        f"Examiner questions:\n{questions}\n\n"
        f"Fluency metrics (computed by backend — do not change):\n"
        f"{json.dumps(fluency_metrics, indent=2)}\n\n"
        f"Transcript:\n{transcript}\n\n"
        "Return evaluation JSON only."
    )
