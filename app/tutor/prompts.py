"""System / user prompt builders for contextual writing tutoring."""

from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = """You are MATA Coach, an IELTS Writing tutor for BandForge.

Rules:
1. Ground every answer in the CONTEXT PACK (this student's essay, scores, mistakes, history).
2. Do NOT give generic IELTS tips that ignore their essay or criteria.
3. When explaining band scores, cite their criterion numbers and improvements.
4. When explaining grammar, quote their mistake (original → correction) when present.
5. For rewrites or Band 8 versions, rewrite THEIR text (selection or essay), then briefly say why it scores higher.
6. For vocabulary, prefer their weak vocabulary_highlights and alternatives.
7. For coherence, use their coherence criterion and related improvements.
8. If context is thin, say what is missing — do not invent scores.
9. Keep replies concise (roughly 120–250 words) unless they ask for a full rewrite.
10. Respond with JSON only: {"reply": "<markdown-friendly text>", "focus": "<short label>"}
"""


def build_user_prompt(
    *,
    context_pack: dict[str, Any],
    message: str,
    selection: str | None,
    turns: list[dict[str, str]],
) -> str:
    compact = {
        "current": context_pack.get("current"),
        "prior_attempts": context_pack.get("prior_attempts"),
        "learning_profile": context_pack.get("learning_profile"),
    }
    history_lines: list[str] = []
    for turn in turns[-6:]:
        role = turn.get("role", "user")
        content = (turn.get("content") or "")[:1500]
        history_lines.append(f"{role}: {content}")

    parts = [
        "CONTEXT PACK (authoritative — do not contradict):",
        json.dumps(compact, ensure_ascii=False, indent=2)[:14000],
        "",
        "RECENT TURNS:",
        "\n".join(history_lines) if history_lines else "(none)",
        "",
    ]
    if selection and selection.strip():
        parts.extend(
            [
                "STUDENT SELECTION (focus on this excerpt):",
                selection.strip()[:2000],
                "",
            ]
        )
    parts.extend(["STUDENT QUESTION:", message.strip()[:2000]])
    return "\n".join(parts)
