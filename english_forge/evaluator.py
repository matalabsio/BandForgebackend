"""School coach LLM evaluation — school-speaking-v0.2 (no IELTS bands)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.config import get_settings
from app.diagnostic.groq_client import chat_completion_json as groq_chat_json
from app.diagnostic.groq_client import groq_configured
from app.speaking.claude_client import chat_completion_json as claude_chat_json
from app.speaking.claude_client import claude_configured

from .evaluator_stub import evaluate_stub
from .rubric import (
    EVALUATOR_VERSION,
    RUBRIC_VERSION,
    SCHEMA_VERSION,
    class_label,
    get_rubric,
    rubric_system_block,
)
from .schemas import CoachCard, CoachInternalSignals, EvaluateRequest, PrimaryFix

logger = logging.getLogger(__name__)

BASE_SYSTEM_PROMPT = """You are a warm Spoken English coach for school students (Class 1–10).
Return ONLY valid JSON matching this schema:
{
  "understandable": "yes" | "mostly" | "difficult",
  "strength": "one short specific sentence of praise",
  "primary_fix": null | {"before": "...", "after": "...", "why_kid_friendly": "..."},
  "new_words": ["up to 3 age-appropriate words"],
  "filler_note": null | "gentle note",
  "retry_prompt": "next speak task"
}

Shared rules:
- Never give IELTS bands or examiner criterion scores.
- At most ONE primary_fix (or null if excellent/too short to fix usefully).
- Prefer meaning-changing, grade-appropriate errors.
- Do not shame accent, silence, or nervousness.
- Do not invent quotes the student did not say.
- Keep tone kind and actionable.
- Never score similarity to a sample/reference answer. Many valid answers exist for each prompt.
- Judge only the student's transcript against the prompt and the grade rubric below.
"""


def english_forge_eval_stub() -> bool:
    return bool(getattr(get_settings(), "english_forge_eval_stub", False))


def build_system_prompt(grade_band: str) -> str:
    return f"{BASE_SYSTEM_PROMPT}\n{rubric_system_block(grade_band)}"


async def evaluate_coach(req: EvaluateRequest) -> CoachCard:
    if english_forge_eval_stub():
        logger.info("English Forge coach eval using stub (ENGLISH_FORGE_EVAL_STUB)")
        return evaluate_stub(req)

    rubric = get_rubric(req.grade_band)
    system = build_system_prompt(req.grade_band)
    user = (
        f"grade_band: {req.grade_band}\n"
        f"class_label: {class_label(req.grade_band)}\n"
        f"target_duration_sec: {rubric.target_duration_sec}\n"
        f"max_duration_sec: {rubric.max_duration_sec}\n"
        f"prompt: {req.prompt}\n"
        f"duration_sec: {req.duration_sec}\n"
        f"transcript:\n{req.transcript}\n"
        "Evaluate this student's spoken answer for THIS grade band only. "
        "Do not compare to any sample answer. "
        "Apply the band rubric from the system instructions.\n"
    )

    raw: str | None = None
    provider_used = "none"
    errors: list[str] = []

    # Primary: Claude
    if claude_configured():
        try:
            logger.info("English Forge coach eval → Claude (%s)", req.grade_band)
            raw, _ = await claude_chat_json(system=system, user=user)
            provider_used = "claude"
        except Exception as exc:  # noqa: BLE001
            errors.append(f"claude:{exc}")
            logger.warning("English Forge Claude eval failed: %s", exc)

    # Fallback: Groq chat
    if raw is None and groq_configured():
        try:
            logger.info("English Forge coach eval → Groq LLM fallback (%s)", req.grade_band)
            raw, _ = await groq_chat_json(system=system, user=user)
            provider_used = "groq"
        except Exception as exc:  # noqa: BLE001
            errors.append(f"groq:{exc}")
            logger.warning("English Forge Groq eval failed: %s", exc)

    if raw is None:
        if getattr(get_settings(), "ai_budget_fallback_stub", False) or errors:
            logger.warning(
                "English Forge coach eval falling back to stub (%s)",
                "; ".join(errors) or "no provider",
            )
            card = evaluate_stub(req)
            if card.internal_signals:
                card.internal_signals.evaluator_version = "school-speaking-stub-fallback"
            return card
        raise RuntimeError(
            "English Forge coach eval unavailable: " + ("; ".join(errors) or "no LLM configured")
        )

    card = _parse_coach_card(raw, req)
    if card.internal_signals:
        card.internal_signals.evaluator_version = f"{EVALUATOR_VERSION}+{provider_used}"
    return card


def _parse_coach_card(raw: str, req: EvaluateRequest) -> CoachCard:
    data = _extract_json(raw)
    primary = data.get("primary_fix")
    fix: PrimaryFix | None = None
    if isinstance(primary, dict) and primary.get("before") and primary.get("after"):
        fix = PrimaryFix(
            before=str(primary["before"])[:200],
            after=str(primary["after"])[:200],
            why_kid_friendly=str(primary.get("why_kid_friendly") or "Try this clearer sentence.")[:240],
        )

    understandable = str(data.get("understandable") or "mostly")
    if understandable not in ("yes", "mostly", "difficult"):
        understandable = "mostly"

    words = data.get("new_words") or []
    if not isinstance(words, list):
        words = []
    new_words = [str(w).strip() for w in words if str(w).strip()][:3]

    filler = data.get("filler_note")
    filler_note = str(filler).strip() if filler else None

    card = CoachCard(
        understandable=understandable,  # type: ignore[arg-type]
        strength=str(data.get("strength") or "Nice speaking — keep going!")[:200],
        primary_fix=fix,
        new_words=new_words,
        filler_note=filler_note[:240] if filler_note else None,
        retry_prompt=str(data.get("retry_prompt") or f"Try again: {req.prompt}")[:280],
        internal_signals=CoachInternalSignals(
            evaluator_version=EVALUATOR_VERSION,
            rubric_version=RUBRIC_VERSION,
            schema_version=SCHEMA_VERSION,
        ),
    )
    return card


def _extract_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        data = json.loads(match.group(0))
        if isinstance(data, dict):
            return data
    raise ValueError("Coach eval did not return JSON object")
