"""FSP Writing track helpers (users.exam_module).

Purpose may *recommend* a Writing module; exam_module is the selected track.
Writing Skill authorization continues to use user_program_usage.exam_module.
"""

from __future__ import annotations

from typing import Literal

ExamModule = Literal["academic", "general_training"]
VALID_EXAM_MODULES = frozenset({"academic", "general_training"})

# Purpose → soft recommendation only (never an irreversible assignment).
# University → Academic. Every other known purpose → General Training.
PURPOSE_RECOMMENDED_EXAM_MODULE: dict[str, ExamModule] = {
    "university": "academic",
    "immigration": "general_training",
    "professional": "general_training",
    "general": "general_training",
}


def recommend_exam_module(purpose: str | None) -> ExamModule | None:
    """Return a soft recommendation from ielts_purpose, or None if none."""
    if purpose is None:
        return None
    key = str(purpose).strip().lower()
    if not key:
        return None
    return PURPOSE_RECOMMENDED_EXAM_MODULE.get(key)


def requires_explicit_exam_module_choice(purpose: str | None) -> bool:
    """True when purpose has no recommendation badge.

    Known purposes always recommend (university=Academic, else GT). The UI
    still lets the student pick either track.
    """
    if purpose is None:
        return True
    key = str(purpose).strip().lower()
    if not key:
        return True
    return recommend_exam_module(key) is None
