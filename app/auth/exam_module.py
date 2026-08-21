"""FSP Writing track helpers (users.exam_module).

Purpose may *recommend* a Writing module; exam_module is the selected track.
Writing Skill authorization continues to use user_program_usage.exam_module.
"""

from __future__ import annotations

from typing import Literal

ExamModule = Literal["academic", "general_training"]
VALID_EXAM_MODULES = frozenset({"academic", "general_training"})

# Purpose → soft recommendation only (never an irreversible assignment).
PURPOSE_RECOMMENDED_EXAM_MODULE: dict[str, ExamModule] = {
    "university": "academic",
    "immigration": "general_training",
}

# These purposes never auto-recommend; user must choose explicitly.
PURPOSES_REQUIRING_EXPLICIT_CHOICE = frozenset({"professional", "general"})


def recommend_exam_module(purpose: str | None) -> ExamModule | None:
    """Return a soft recommendation from ielts_purpose, or None if none."""
    if purpose is None:
        return None
    key = str(purpose).strip().lower()
    if not key:
        return None
    return PURPOSE_RECOMMENDED_EXAM_MODULE.get(key)


def requires_explicit_exam_module_choice(purpose: str | None) -> bool:
    """True when purpose must not pretreat one module as correct.

    University/immigration still require an explicit UI selection; they only
    surface a recommendation badge. Professional/general have no badge.
    """
    if purpose is None:
        return True
    key = str(purpose).strip().lower()
    if not key:
        return True
    if key in PURPOSES_REQUIRING_EXPLICIT_CHOICE:
        return True
    return recommend_exam_module(key) is None
