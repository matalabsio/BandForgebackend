"""IELTS writing band helpers for evaluator portal."""

from __future__ import annotations

from typing import Any

CRITERIA_KEYS = ("task_achievement", "coherence", "lexical_resource", "grammar")


def round_half(value: float) -> float:
    return round(value * 2) / 2


def compute_overall_band(scores: dict[str, Any]) -> float:
    """Mean of four criteria, rounded to nearest 0.5 (IELTS-style)."""
    if any(key not in scores or scores[key] is None for key in CRITERIA_KEYS):
        raise ValueError("All four criteria scores are required.")
    values = [float(scores[key]) for key in CRITERIA_KEYS]
    return round_half(sum(values) / len(values))


def normalize_criteria_scores(raw: dict[str, Any] | None) -> dict[str, float] | None:
    if not raw:
        return None
    out: dict[str, float] = {}
    for key in CRITERIA_KEYS:
        if key not in raw or raw[key] is None:
            return None
        out[key] = float(raw[key])
    return out


def ai_scores_to_criteria(ai_scores: dict[str, Any] | None) -> dict[str, float] | None:
    """Map ai_scores / criteria_scores jsonb to rubric criteria."""
    if not ai_scores:
        return None
    nested = ai_scores.get("criteria_scores")
    if not isinstance(nested, dict):
        nested = ai_scores.get("criteria")
    if isinstance(nested, dict):
        ai_scores = nested
    mapped = {
        "task_achievement": ai_scores.get("task_achievement"),
        "coherence": ai_scores.get("coherence"),
        "lexical_resource": ai_scores.get("lexical_resource"),
        "grammar": ai_scores.get("grammar"),
    }
    if any(v is None for v in mapped.values()):
        return None
    return {k: float(v) for k, v in mapped.items()}
