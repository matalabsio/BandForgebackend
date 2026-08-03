"""Bidirectional mapping between UI display names and DB slugs for reading question types."""

from __future__ import annotations

UI_TO_SLUG: dict[str, str] = {
    "True/False/Not Given": "tfng",
    "Yes/No/Not Given": "ynng",
    "Multiple choice": "mcq",
    "Matching headings": "matching_headings",
    "Matching information": "matching_information",
    "Matching features": "matching_features",
    "Matching sentence endings": "matching_sentence_endings",
    "Summary completion (from box)": "summary_completion_box",
    "Summary completion (from passage)": "summary_completion_passage",
    "Note completion": "note_completion",
    "Table completion": "table_completion",
    "Flow-chart completion": "flowchart_completion",
    "Short answer questions": "short_answer",
    "Sentence completion": "sentence_completion",
}

SLUG_TO_UI: dict[str, str] = {v: k for k, v in UI_TO_SLUG.items()}

ALL_SLUGS = set(UI_TO_SLUG.values())


def to_slug(name: str) -> str:
    """Convert a UI display name or slug to its canonical DB slug."""
    if name in UI_TO_SLUG:
        return UI_TO_SLUG[name]
    if name in ALL_SLUGS:
        return name
    return name


def to_display(slug: str) -> str:
    """Convert a DB slug to its UI display name."""
    return SLUG_TO_UI.get(slug, slug)
