"""Static 'what to practise next' from weakest skill tags (Phase A — no Claude)."""

from __future__ import annotations

from app.listening.schemas import SkillBreakdownEntry

_SKILL_ADVICE: dict[str, str] = {
    "detail": "form completion and specific facts (names, numbers, dates)",
    "form_completion": "writing short answers within the word limit while the audio plays",
    "mcq": "multiple-choice questions and eliminating distractors",
    "map_labeling": "following directions and map labelling",
    "matching": "matching speakers to opinions or categories",
    "note_completion": "note completion and lecture keywords",
    "sentence_completion": "sentence completion and grammar fit",
    "summary_completion": "summary completion and paraphrase recognition",
    "general": "listening for key details under time pressure",
}


def build_practice_tip(
    skill_breakdown: dict[str, SkillBreakdownEntry],
    *,
    max_words: int = 60,
) -> str:
    if not skill_breakdown:
        return (
            "Review the questions you missed and replay the section mentally. "
            "Focus on spelling, numbers, and the two-word answer limit."
        )

    ranked = sorted(
        skill_breakdown.items(),
        key=lambda item: (item[1].pct, -item[1].total),
    )
    weakest = ranked[:2]
    parts: list[str] = []
    for skill, entry in weakest:
        pct = int(round(entry.pct * 100))
        advice = _SKILL_ADVICE.get(skill.lower(), skill.replace("_", " "))
        parts.append(f"{skill.replace('_', ' ')} ({pct}%): {advice}")

    tip = (
        "Focus next on "
        + " and ".join(parts)
        + ". Practise with one timed listening section and check answers immediately."
    )
    words = tip.split()
    if len(words) > max_words:
        return " ".join(words[:max_words]) + "…"
    return tip
