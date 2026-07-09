"""Pydantic models for locked Speaking evaluation JSON (Phase C)."""

from __future__ import annotations

import json
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def _round_band(value: float) -> float:
    clamped = max(0.0, min(9.0, float(value)))
    return round(clamped * 2) / 2


class BandScores(BaseModel):
    FC: float
    LR: float
    GRA: float
    P: float
    P_confidence: float = Field(ge=0.0, le=1.0)
    overall: float

    @field_validator("FC", "LR", "GRA", "P", "overall")
    @classmethod
    def validate_band(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("Band must be finite")
        return _round_band(v)


class PartPerformance(BaseModel):
    part: int = Field(ge=1, le=3)
    note: str = Field(min_length=1)
    band_estimate: float

    @field_validator("band_estimate")
    @classmethod
    def validate_part_band(cls, v: float) -> float:
        return _round_band(v)


class EvidenceQuote(BaseModel):
    quote: str = Field(min_length=1)
    criterion: Literal["FC", "LR", "GRA", "P"]
    polarity: Literal["strength", "weakness"]
    part: int = Field(ge=1, le=3)


class RecurringPattern(BaseModel):
    pattern: str = Field(min_length=1)
    criterion: Literal["FC", "LR", "GRA", "P"]
    frequency: Literal["rare", "sometimes", "often"]
    examples: list[str] = Field(min_length=1, max_length=5)


class SpeakingEvaluation(BaseModel):
    band_scores: BandScores
    part_performance: list[PartPerformance] = Field(min_length=1, max_length=3)
    evidence_quotes: list[EvidenceQuote] = Field(min_length=4, max_length=8)
    recurring_patterns: list[RecurringPattern] = Field(min_length=1, max_length=6)
    strengths: list[str] = Field(min_length=1, max_length=6)
    improvements: list[str] = Field(min_length=1, max_length=6)
    vocabulary_highlights: list[str] = Field(min_length=1, max_length=8)
    reviewer_flags: list[str] = Field(default_factory=list, max_length=8)
    next_band_advice: str = Field(min_length=1)

    @field_validator(
        "strengths",
        "improvements",
        "vocabulary_highlights",
        "reviewer_flags",
    )
    @classmethod
    def strip_strings(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v if s and s.strip()]


def parse_json_content(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Evaluation JSON must be an object")
    return parsed


def coerce_speaking_evaluation_payload(
    parsed: dict[str, Any],
    *,
    part: int,
    transcript: str,
) -> dict[str, Any]:
    """Normalize common LLM JSON mistakes before Pydantic validation."""
    data = dict(parsed)
    snippet = (transcript[:60] if transcript else "response").strip()

    part_perf = data.get("part_performance") or []
    fixed_parts: list[dict[str, Any]] = []
    for item in part_perf:
        if isinstance(item, dict):
            row = dict(item)
            try:
                row["part"] = int(row.get("part", part))
            except (TypeError, ValueError):
                row["part"] = part
            fixed_parts.append(row)
    if not fixed_parts:
        fixed_parts = [
            {
                "part": part,
                "note": "Response addressed the question.",
                "band_estimate": data.get("band_scores", {}).get("overall", 6.0),
            }
        ]
    data["part_performance"] = fixed_parts

    quotes = data.get("evidence_quotes") or []
    fixed_quotes: list[dict[str, Any]] = []
    criteria_cycle = ["FC", "LR", "GRA", "P"]
    polarities = ["strength", "strength", "weakness", "strength"]
    for i, item in enumerate(quotes):
        if isinstance(item, str):
            item = {"quote": item}
        if not isinstance(item, dict):
            continue
        row = dict(item)
        if not row.get("quote"):
            row["quote"] = snippet
        row.setdefault("criterion", criteria_cycle[i % 4])
        row.setdefault("polarity", polarities[i % 4])
        row.setdefault("part", part)
        fixed_quotes.append(row)
    while len(fixed_quotes) < 4:
        idx = len(fixed_quotes)
        fixed_quotes.append(
            {
                "quote": snippet,
                "criterion": criteria_cycle[idx % 4],
                "polarity": polarities[idx % 4],
                "part": part,
            }
        )
    data["evidence_quotes"] = fixed_quotes[:8]

    patterns = data.get("recurring_patterns") or []
    fixed_patterns: list[dict[str, Any]] = []
    for item in patterns:
        if isinstance(item, str):
            fixed_patterns.append(
                {
                    "pattern": item,
                    "criterion": "GRA",
                    "frequency": "sometimes",
                    "examples": ["example"],
                }
            )
        elif isinstance(item, dict):
            row = dict(item)
            row.setdefault("criterion", "GRA")
            row.setdefault("frequency", "sometimes")
            if not row.get("examples"):
                row["examples"] = ["example"]
            fixed_patterns.append(row)
    if not fixed_patterns:
        fixed_patterns = [
            {
                "pattern": "Uses simple structures",
                "criterion": "GRA",
                "frequency": "often",
                "examples": ["basic linking"],
            }
        ]
    data["recurring_patterns"] = fixed_patterns

    for key, default in (
        ("strengths", ["Clear main ideas."]),
        ("improvements", ["Add one concrete example per answer."]),
        ("vocabulary_highlights", ["topic words"]),
    ):
        if not data.get(key):
            data[key] = default

    if not data.get("next_band_advice"):
        data["next_band_advice"] = "Extend answers with examples and clearer structure."

    data.setdefault("reviewer_flags", [])

    return data


def validate_quotes_in_transcript(
    evaluation: SpeakingEvaluation,
    transcript: str,
) -> None:
    """Raise ValueError if any evidence quote is not an exact transcript substring."""
    for item in evaluation.evidence_quotes:
        if item.quote not in transcript:
            raise ValueError(
                f"evidence_quotes.quote not found in transcript: {item.quote!r}"
            )


def evaluation_to_admin_criteria(evaluation: SpeakingEvaluation) -> dict[str, float]:
    """Map locked schema to admin portal top-level criteria keys."""
    bs = evaluation.band_scores
    return {
        "fluency": bs.FC,
        "lexical": bs.LR,
        "grammar": bs.GRA,
        "pronunciation": bs.P,
    }


def build_stub_evaluation(
    *,
    transcript: str,
    part: int = 1,
) -> SpeakingEvaluation:
    """Schema-valid stub for SPEAKING_EVAL_STUB mode."""
    snippet = transcript[:80] if len(transcript) >= 20 else transcript or "I think this is important."
    return SpeakingEvaluation(
        band_scores=BandScores(
            FC=6.0,
            LR=6.0,
            GRA=5.5,
            P=6.0,
            P_confidence=0.6,
            overall=6.0,
        ),
        part_performance=[
            PartPerformance(
                part=part,
                note="Stub evaluation — replace with live Claude output.",
                band_estimate=6.0,
            )
        ],
        evidence_quotes=[
            EvidenceQuote(
                quote=snippet,
                criterion="FC",
                polarity="strength",
                part=part,
            ),
            EvidenceQuote(
                quote=snippet,
                criterion="LR",
                polarity="strength",
                part=part,
            ),
            EvidenceQuote(
                quote=snippet,
                criterion="GRA",
                polarity="weakness",
                part=part,
            ),
            EvidenceQuote(
                quote=snippet,
                criterion="P",
                polarity="strength",
                part=part,
            ),
        ],
        recurring_patterns=[
            RecurringPattern(
                pattern="Uses simple sentence structures",
                criterion="GRA",
                frequency="often",
                examples=["basic linking"],
            )
        ],
        strengths=["Clear enough to follow the main idea."],
        improvements=["Extend answers with one concrete example each time."],
        vocabulary_highlights=["topic vocabulary"],
        reviewer_flags=["stub_evaluation"],
        next_band_advice="Practice timed answers with point-example-conclusion structure.",
    )
