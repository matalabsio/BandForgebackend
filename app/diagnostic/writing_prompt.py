"""Versioned IELTS writing examiner prompts for diagnostic evaluation.

Prompts are loaded from versioned files under app/writing/prompts/ via PromptLoader.
This module keeps the stable public API used by evaluation_call and tests.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.writing.prompt_loader import (
    DEFAULT_PROMPT_VERSION,
    LoadedPrompt,
    load_writing_prompt,
)


def resolve_prompt_version(override: str | None = None) -> str:
    """Active writing prompt version (settings or explicit override)."""
    if override and override.strip():
        ver = override.strip()
    else:
        settings = get_settings()
        ver = (settings.writing_prompt_version or DEFAULT_PROMPT_VERSION).strip()
    # Legacy DIAGNOSTIC default was "v1" — treat as current default.
    if ver in ("", "v1"):
        return DEFAULT_PROMPT_VERSION
    return ver


@lru_cache(maxsize=8)
def _cached_prompt(version: str) -> LoadedPrompt:
    return load_writing_prompt(version)


def get_loaded_prompt(version: str | None = None) -> LoadedPrompt:
    return _cached_prompt(resolve_prompt_version(version))


def get_system_prompt(version: str | None = None) -> str:
    return get_loaded_prompt(version).system


def get_task1_rules(version: str | None = None) -> str:
    return get_loaded_prompt(version).task1_rules or ""


# Backward-compatible module constants (default v5 at import).
PROMPT_VERSION = DEFAULT_PROMPT_VERSION
_loaded = load_writing_prompt(PROMPT_VERSION)
SYSTEM_PROMPT_V4 = _loaded.system
SYSTEM_PROMPT = SYSTEM_PROMPT_V4
TASK1_RULES_BLOCK = _loaded.task1_rules or ""


def build_user_prompt(
    *,
    task_part: int,
    question: str,
    essay: str,
    visual_description: str | None = None,
    word_count: int | None = None,
    target_band: float | None = None,
) -> str:
    """Assemble the examiner user message (question + optional T1 visual + essay + meta)."""
    task_label = "Task 1 (Academic)" if task_part == 1 else "Task 2 (Academic)"
    parts = [
        f"Evaluate this IELTS {task_label} response.",
        "",
        "Question:",
        question.strip(),
    ]

    visual = (visual_description or "").strip()
    if task_part == 1 and visual:
        parts.extend(["", "Visual / chart description:", visual])

    parts.extend(["", "Student essay:", essay.strip()])

    meta_lines: list[str] = []
    if word_count is not None and word_count >= 0:
        meta_lines.append(f"Word count: {word_count}")
    if target_band is not None and target_band > 0:
        meta_lines.append(f"Target band: {target_band:g}")
        meta_lines.append(
            "Use Target band only to personalise next_band_advice "
            "(e.g. aim language toward that band). Do not inflate criterion scores."
        )
    if meta_lines:
        parts.extend(["", "Metadata:"] + meta_lines)

    parts.extend(["", "Return JSON only."])
    return "\n".join(parts)


RETRY_SUFFIX = (
    "\n\nYour previous response was invalid. Return ONLY valid JSON matching "
    "the required schema. No markdown fences, no extra keys, no commentary."
)
