"""Admin answer storage contract (Phase 3).

- Slash ``/`` joins OR alternatives (primary/alt1/alt2) for a single question.
- Choose TWO is **two (or more) question rows**, each with one letter — never
  ``A,B`` or ``AB`` in ``correct_answer``.
- Comma-separated letters from the admin UI are expanded on save only.
"""

from __future__ import annotations

import re
from typing import Any

_LETTER = re.compile(r"^[A-Za-z]$")


def join_answers(primary: str, alts: list[str] | None = None) -> str:
    """Join primary + alt answers with ``/`` (OR alternatives)."""
    parts = [primary.strip()] + [a.strip() for a in (alts or []) if a.strip()]
    return "/".join(parts) if parts else ""


def split_answers(raw: str | None) -> tuple[str, list[str]]:
    """Split ``primary/alt1/alt2`` into primary + alts."""
    if not raw:
        return "", []
    parts = [p.strip() for p in str(raw).split("/") if p.strip()]
    if not parts:
        return "", []
    return parts[0], parts[1:]


def parse_choose_two_letters(raw: str | None) -> list[str]:
    """Parse admin choose-two payload into ordered single letters.

    Accepts comma-separated (``A,B``), slash-separated when all parts are
    single letters (``A/B`` from mistaken join), or a bare letter.
    Rejects concatenated ``AB``.
    """
    if not raw:
        return []
    text = str(raw).strip()
    if not text:
        return []

    # Concatenated two letters without separator — reject / ignore as multi
    if _LETTER.match(text):
        return [text.upper()]

    if "," in text:
        parts = [p.strip().upper() for p in text.split(",") if p.strip()]
    elif "/" in text:
        parts = [p.strip().upper() for p in text.split("/") if p.strip()]
    else:
        # "AB" or longer — not a valid choose-two cell
        return []

    letters = [p for p in parts if _LETTER.match(p)]
    return letters if len(letters) >= 2 else ([] if len(letters) == 0 else letters)


def expand_choose_two_rows(
    *,
    base: dict[str, Any],
    correct_answer: str,
    alt_answers: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Expand one choose-two admin question into N single-letter rows.

    ``base`` should already contain module/part/prompt/options/etc.
    Each output row gets ``correct_answer`` = one letter (no alts).
    """
    letters = parse_choose_two_letters(correct_answer)
    if len(letters) < 2:
        # Fallback: treat as single mcq with slash alts
        row = {
            **base,
            "correct_answer": join_answers(correct_answer, alt_answers or []),
        }
        return [row]

    return [
        {
            **base,
            "correct_answer": letter,
            "question_type": "mcq",
        }
        for letter in letters
    ]


def looks_like_choose_two_pair(
    a: dict[str, Any],
    b: dict[str, Any],
) -> bool:
    """True when two consecutive mcq rows share prompt+options (exam choose-two)."""
    if str(a.get("question_type") or "") != "mcq":
        return False
    if str(b.get("question_type") or "") != "mcq":
        return False
    if (a.get("prompt") or "") != (b.get("prompt") or ""):
        return False
    ca = str(a.get("correct_answer") or "").strip()
    cb = str(b.get("correct_answer") or "").strip()
    if not (_LETTER.match(ca) and _LETTER.match(cb)):
        return False
    # Options equality (best-effort)
    return (a.get("options") or []) == (b.get("options") or [])
