"""Shared helpers for writing AI evaluation (no provider imports)."""

from __future__ import annotations

import hashlib
import re

from app.writing.evaluation import word_count

MIN_WORDS_FOR_AI = 30


def normalize_text(text: str) -> str:
    return " ".join(text.strip().split())


def sanitize_essay(essay: str, question: str) -> str:
    """Strip pasted task instructions so word count and scoring target the response."""
    text = essay.strip()
    if not text:
        return text

    question_text = question.strip()
    if question_text and question_text in text:
        text = text.replace(question_text, "", 1).strip()

    boilerplate_patterns = [
        r"You should spend about \d+ minutes on this task\.?\s*",
        r"Summarise the information by selecting and reporting the main features.*?\.\s*",
        r"Write at least \d+ words\.?\s*",
        r"The (?:bar chart|chart|graph|table|diagram) below shows.*?\.\s*",
    ]
    for pattern in boilerplate_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL)

    return text.strip() or essay.strip()


def compute_essay_hash(
    *,
    task_part: int,
    question: str,
    essay: str,
    prompt_version: str = "",
    model_name: str = "",
    visual_description: str = "",
) -> str:
    """Stable cache key; prompt_version + model_name isolate version swaps."""
    payload = (
        f"{task_part}\n{normalize_text(question)}\n{normalize_text(essay)}\n"
        f"{normalize_text(visual_description)}\n"
        f"{(prompt_version or '').strip()}\n{(model_name or '').strip()}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def writing_cache_model_key() -> str:
    """Model identity used in essay_hash before/without a live provider call."""
    from app.config import get_settings
    from app.writing.providers.constants import PROVIDER_NAME_STUB

    settings = get_settings()
    if settings.writing_eval_stub:
        return PROVIDER_NAME_STUB
    primary = (settings.writing_llm_primary or "").strip().lower()
    if primary == "claude":
        return settings.anthropic_model or "claude"
    if primary == "groq":
        return settings.groq_model or "groq"
    if primary in ("", "none"):
        return PROVIDER_NAME_STUB
    return primary


def visual_description_from_task_options(
    options: dict | None,
    *,
    part: int,
) -> str:
    """Build a text chart/figure description for Task 1 examiner context (no image URLs)."""
    if part != 1 or not isinstance(options, dict):
        return ""

    chunks: list[str] = []
    figure_label = options.get("figure_label")
    if isinstance(figure_label, str) and figure_label.strip():
        chunks.append(figure_label.strip())

    figure_note = options.get("figure_note")
    if isinstance(figure_note, str) and figure_note.strip():
        chunks.append(figure_note.strip())

    chart = options.get("chart") or options.get("chart_data") or options.get("figure")
    if isinstance(chart, dict):
        title = chart.get("title")
        if isinstance(title, str) and title.strip():
            chunks.append(title.strip())
        chart_type = chart.get("type")
        if isinstance(chart_type, str) and chart_type.strip():
            chunks.append(f"Chart type: {chart_type.strip()}")
        cities = chart.get("cities")
        if isinstance(cities, list) and cities:
            labels = ", ".join(str(c) for c in cities if c is not None)
            if labels:
                chunks.append(f"Categories / cities: {labels}")
        labels = chart.get("labels")
        if isinstance(labels, list) and labels:
            axis = ", ".join(str(x) for x in labels if x is not None)
            if axis:
                chunks.append(f"X-axis labels: {axis}")
        series = chart.get("series")
        if isinstance(series, list) and series:
            names: list[str] = []
            for s in series:
                if isinstance(s, dict):
                    name = s.get("label") or s.get("mode")
                    if name:
                        names.append(str(name))
            if names:
                chunks.append(f"Series: {', '.join(names)}")

    # Dedupe while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for chunk in chunks:
        key = chunk.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(chunk)
    return "\n".join(unique)


def count_sentences(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    parts = re.split(r"[.!?]+", stripped)
    return max(1, sum(1 for part in parts if part.strip()))


def count_paragraphs(text: str) -> int:
    if not text.strip():
        return 0
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    return max(1, len(paras))


__all__ = [
    "MIN_WORDS_FOR_AI",
    "compute_essay_hash",
    "count_paragraphs",
    "count_sentences",
    "normalize_text",
    "sanitize_essay",
    "visual_description_from_task_options",
    "word_count",
    "writing_cache_model_key",
]
