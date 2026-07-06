"""Normalize listening question instructions from DB passage_text."""

from __future__ import annotations

import re
from typing import Any

_BOX_CHARS = frozenset("╔╠╚║═╗╝╣╦╩┌┐└┘│─")
_NOTES_MARKER_PREFIX = "@@notes_"
_FORM_TITLE_MARKER = "@@form_title@@"
_SECTION_MARKER = "@@section@@"
_SECTION_RE = re.compile(
    r"^@@section@@(?P<start>\d+)(?:-(?P<end>\d+))?\|(?P<heading>.+)$"
)


def _line_has_box_art(line: str) -> bool:
    return any(c in _BOX_CHARS for c in line)


def _is_meta_marker(line: str) -> bool:
    return line.startswith(_NOTES_MARKER_PREFIX) or line.startswith(_FORM_TITLE_MARKER)


def extract_listening_instructions(passage_text: str | None) -> str | None:
    """Return exam-facing instructions only (no form templates or notes meta)."""
    if not passage_text or not str(passage_text).strip():
        return None
    lines: list[str] = []
    for raw in str(passage_text).splitlines():
        if _line_has_box_art(raw):
            break
        stripped = raw.strip()
        if not stripped:
            continue
        if _is_meta_marker(stripped):
            break
        # Normalizer form style: title paragraph before instruction.
        if not lines and "FORM" in stripped.upper() and not stripped.lower().startswith(
            ("complete", "write", "questions", "choose")
        ):
            continue
        lines.append(stripped)
    if not lines:
        return None
    return "\n".join(lines)


def extract_form_title(passage_text: str | None) -> str | None:
    """Form header title from markers, normalizer title line, or ASCII box art."""
    if not passage_text or not str(passage_text).strip():
        return None
    first_content: str | None = None
    for raw in str(passage_text).splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith(_FORM_TITLE_MARKER):
            title = stripped[len(_FORM_TITLE_MARKER) :].strip()
            return title or None
        if _line_has_box_art(raw):
            inner = "".join(c for c in stripped if c not in _BOX_CHARS).strip()
            if "FORM" in inner.upper() and len(inner) > 4:
                return inner
            continue
        if _is_meta_marker(stripped):
            continue
        if first_content is None:
            first_content = stripped
    if first_content and "FORM" in first_content.upper():
        return first_content
    return None


def extract_notes_layout(passage_text: str | None) -> dict[str, Any]:
    """Parse notes_title and notes_sections markers from passage_text."""
    title: str | None = None
    sections: list[dict[str, Any]] = []
    if not passage_text or not str(passage_text).strip():
        return {"notes_title": None, "notes_sections": None}
    for raw in str(passage_text).splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("@@notes_title@@"):
            title = stripped[len("@@notes_title@@") :].strip() or None
            continue
        match = _SECTION_RE.match(stripped)
        if match:
            start = int(match.group("start"))
            end_raw = match.group("end")
            end = int(end_raw) if end_raw else start
            heading = match.group("heading").strip()
            if heading:
                sections.append({"heading": heading, "start": start, "end": end})
    return {
        "notes_title": title,
        "notes_sections": sections or None,
    }
