"""AI vs human score comparison helpers for approve audit + analytics."""

from __future__ import annotations

from typing import Any

OVERRIDE_THRESHOLD = 0.5


def round_half(value: float) -> float:
    return round(value * 2) / 2


def delta_between(human: float | None, ai: float | None) -> float | None:
    if human is None or ai is None:
        return None
    return round_half(human - ai)


def is_overridden(
    *,
    human_criteria: dict[str, Any] | None,
    ai_criteria: dict[str, Any] | None,
    human_overall: float | None = None,
    ai_overall: float | None = None,
) -> bool:
    """True if any criterion |Δ| ≥ 0.5 or overall |Δ| ≥ 0.5."""
    if human_criteria and ai_criteria:
        for key, human_val in human_criteria.items():
            if human_val is None or key not in ai_criteria or ai_criteria[key] is None:
                continue
            d = delta_between(float(human_val), float(ai_criteria[key]))
            if d is not None and abs(d) >= OVERRIDE_THRESHOLD:
                return True
    d_overall = delta_between(human_overall, ai_overall)
    return d_overall is not None and abs(d_overall) >= OVERRIDE_THRESHOLD


def approve_audit_metadata(
    *,
    human_band: float,
    human_criteria: dict[str, Any],
    ai_band: float | None,
    ai_criteria: dict[str, Any] | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    delta_overall = delta_between(human_band, ai_band)
    meta: dict[str, Any] = {
        "human_band": human_band,
        "human_criteria_scores": human_criteria,
        "ai_band": ai_band,
        "ai_criteria": ai_criteria,
        "overridden": is_overridden(
            human_criteria=human_criteria,
            ai_criteria=ai_criteria,
            human_overall=human_band,
            ai_overall=ai_band,
        ),
        "delta_overall": delta_overall,
    }
    if extra:
        meta.update(extra)
    return meta


def mae(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(abs(v) for v in values) / len(values), 3)
