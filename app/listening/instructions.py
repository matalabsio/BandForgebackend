"""Normalize listening question instructions from DB passage_text."""

from __future__ import annotations

_BOX_CHARS = frozenset("╔╠╚║═╗╝╣╦╩┌┐└┘│─")


def _line_has_box_art(line: str) -> bool:
    return any(c in _BOX_CHARS for c in line)


def extract_listening_instructions(passage_text: str | None) -> str | None:
    """Return exam-facing instructions only (no embedded ASCII form templates)."""
    if not passage_text or not str(passage_text).strip():
        return None
    lines: list[str] = []
    for raw in str(passage_text).splitlines():
        if _line_has_box_art(raw):
            break
        stripped = raw.strip()
        if stripped:
            lines.append(stripped)
    if not lines:
        return None
    return "\n".join(lines)
