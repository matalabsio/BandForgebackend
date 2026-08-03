"""Bidirectional mapping for listening question types (admin UI ↔ DB slugs)."""

from __future__ import annotations

LISTENING_UI_TO_SLUG: dict[str, str] = {
    "Form completion": "form_completion",
    "Note completion": "note_completion",
    "Sentence completion": "sentence_completion",
    "MCQ — single answer": "mcq",
    "MCQ — choose TWO": "mcq",
    "Matching": "matching",
    "Table completion": "table_completion",
    "Map/plan/diagram labelling": "map_labeling",
    "Flow-chart completion": "flowchart_completion",
    "Summary completion": "summary_completion_box",
}

# Prefer specific UI labels when reversing (mcq → single by default)
LISTENING_SLUG_TO_UI: dict[str, str] = {
    "form_completion": "Form completion",
    "note_completion": "Note completion",
    "sentence_completion": "Sentence completion",
    "mcq": "MCQ — single answer",
    "matching": "Matching",
    "table_completion": "Table completion",
    "map_labeling": "Map/plan/diagram labelling",
    "flowchart_completion": "Flow-chart completion",
    "summary_completion_box": "Summary completion",
}

LISTENING_ALL_SLUGS = set(LISTENING_UI_TO_SLUG.values())

# Types that use multi-select (choose TWO) — stored as mcq with comma-joined answers
MCQ_CHOOSE_TWO_UI = "MCQ — choose TWO"


def listening_to_slug(name: str) -> str:
    if name in LISTENING_UI_TO_SLUG:
        return LISTENING_UI_TO_SLUG[name]
    if name in LISTENING_ALL_SLUGS:
        return name
    return name


def listening_to_display(slug: str, *, choose_two: bool = False) -> str:
    if choose_two and slug == "mcq":
        return MCQ_CHOOSE_TWO_UI
    return LISTENING_SLUG_TO_UI.get(slug, slug)
