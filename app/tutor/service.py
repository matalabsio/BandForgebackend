"""Tutor chat service — contextual writing coaching."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.ai_ops.budget import (
    check_claude_budget,
    check_groq_budget,
    consume_claude_eval,
    consume_groq_eval,
)
from app.ai_ops.circuit import is_claude_circuit_open
from app.config import get_settings
from app.tutor.context import build_context_pack, used_context_summary
from app.tutor.prompts import SYSTEM_PROMPT, build_user_prompt
from app.tutor.schemas import (
    TutorChatRequest,
    TutorChatResponse,
    TutorSuggestion,
    TutorSuggestionsResponse,
    TutorUsedContext,
)
from app.tutor.stub import stub_tutor_chat_json, stub_tutor_reply
from app.writing.providers.constants import (
    PROVIDER_NAME_STUB,
    WritingLLMProviderKind,
)
from app.writing.providers.claude_eval import ClaudeWritingProvider
from app.writing.providers.groq_eval import GroqWritingProvider

logger = logging.getLogger(__name__)

MAX_TURNS = 6

STATIC_SUGGESTIONS: list[TutorSuggestion] = [
    TutorSuggestion(
        id="why_band",
        label="Why this band?",
        message="Why did I get this band on my essay?",
    ),
    TutorSuggestion(
        id="grammar",
        label="Explain grammar",
        message="Explain this grammar mistake from my report.",
    ),
    TutorSuggestion(
        id="rewrite",
        label="Rewrite paragraph",
        message="Rewrite my last paragraph more clearly.",
    ),
    TutorSuggestion(
        id="band8",
        label="Band 8 version",
        message="Give a Band 8 version of my essay opening.",
    ),
    TutorSuggestion(
        id="vocab",
        label="Stronger vocabulary",
        message="Suggest stronger vocabulary for the weak words in my essay.",
    ),
    TutorSuggestion(
        id="coherence",
        label="Explain coherence",
        message="Explain my coherence score and how to improve it in this essay.",
    ),
]


def _parse_kind(raw: str) -> WritingLLMProviderKind:
    normalized = (raw or WritingLLMProviderKind.CLAUDE.value).strip().lower()
    try:
        return WritingLLMProviderKind(normalized)
    except ValueError:
        return WritingLLMProviderKind.NONE


def _provider_for_kind(kind: WritingLLMProviderKind):
    match kind:
        case WritingLLMProviderKind.CLAUDE:
            return ClaudeWritingProvider()
        case WritingLLMProviderKind.GROQ:
            return GroqWritingProvider()
        case _:
            return None


def _use_stub() -> bool:
    settings = get_settings()
    if settings.writing_eval_stub:
        return True
    return False


def _extract_json_obj(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


async def _live_chat(
    *,
    context_pack: dict[str, Any],
    message: str,
    selection: str | None,
    turns: list[dict[str, str]],
) -> tuple[str, str, bool]:
    settings = get_settings()
    user_prompt = build_user_prompt(
        context_pack=context_pack,
        message=message,
        selection=selection,
        turns=turns,
    )

    primary = _parse_kind(settings.writing_llm_primary)
    fallback = _parse_kind(settings.writing_llm_fallback)
    chain: list[WritingLLMProviderKind] = []
    if primary != WritingLLMProviderKind.NONE:
        chain.append(primary)
    if fallback != WritingLLMProviderKind.NONE and fallback not in chain:
        chain.append(fallback)

    budget = check_claude_budget()
    groq_budget = check_groq_budget()
    circuit = is_claude_circuit_open()
    skip_claude = (not budget.ok) or circuit.open
    skip_groq = not groq_budget.ok

    last_error: Exception | None = None
    for kind in chain:
        if kind == WritingLLMProviderKind.CLAUDE and skip_claude:
            logger.warning("Tutor skip Claude: budget/circuit")
            continue
        if kind == WritingLLMProviderKind.GROQ and skip_groq:
            logger.warning("Tutor skip Groq: %s", groq_budget.reason or "budget")
            continue
        provider = _provider_for_kind(kind)
        if provider is None or not provider.configured():
            continue
        try:
            if kind == WritingLLMProviderKind.CLAUDE:
                consume_claude_eval()
            elif kind == WritingLLMProviderKind.GROQ:
                consume_groq_eval()
            content, _raw = await provider.chat_json(system=SYSTEM_PROMPT, user=user_prompt)
            data = _extract_json_obj(content)
            if data and data.get("reply"):
                return str(data["reply"]).strip(), provider.name, False
            if content.strip():
                return content.strip()[:4000], provider.name, False
        except Exception as exc:
            last_error = exc
            logger.warning("Tutor provider %s failed: %s", kind.value, exc)

    if settings.ai_budget_fallback_stub:
        reply = stub_tutor_reply(
            context_pack=context_pack, message=message, selection=selection
        )["reply"]
        return reply, PROVIDER_NAME_STUB, True

    detail = "Tutor unavailable right now."
    if last_error:
        detail = f"Tutor unavailable ({last_error})."
    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)


async def chat(user_id: UUID, body: TutorChatRequest) -> TutorChatResponse:
    pack = build_context_pack(attempt_id=body.attempt_id, user_id=user_id)
    summary = used_context_summary(pack)
    if not summary.get("has_essay"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Essay text is missing for this attempt — tutoring unavailable.",
        )

    turns = [
        {"role": t.role, "content": t.content}
        for t in body.turns[-MAX_TURNS:]
        if t.role in ("user", "assistant") and t.content.strip()
    ]

    if _use_stub():
        content, _raw = stub_tutor_chat_json(
            context_pack=pack,
            message=body.message,
            selection=body.selection,
        )
        data = _extract_json_obj(content) or {}
        reply = str(data.get("reply") or "").strip()
        provider = PROVIDER_NAME_STUB
        is_stub = True
    else:
        reply, provider, is_stub = await _live_chat(
            context_pack=pack,
            message=body.message,
            selection=body.selection,
            turns=turns,
        )

    return TutorChatResponse(
        reply=reply,
        used_context=TutorUsedContext.model_validate(summary),
        provider=provider,
        stub=is_stub,
    )


def suggestions_for_user(user_id: UUID, attempt_id: UUID | None) -> TutorSuggestionsResponse:
    items = list(STATIC_SUGGESTIONS)
    if attempt_id is not None:
        try:
            pack = build_context_pack(attempt_id=attempt_id, user_id=user_id)
            weaknesses = (pack.get("learning_profile") or {}).get("top_weaknesses") or []
            for w in weaknesses[:2]:
                if not isinstance(w, dict):
                    continue
                label = str(w.get("label") or "")[:64]
                if not label:
                    continue
                items.append(
                    TutorSuggestion(
                        id=f"weak-{abs(hash(label)) % 10_000}",
                        label=label[:40],
                        message=f"Help me improve this weakness on my essay: {label}",
                    )
                )
            grammar = (pack.get("current") or {}).get("grammar_mistakes") or []
            if grammar:
                g0 = grammar[0]
                orig = str(g0.get("original") or "")[:80]
                if orig:
                    items.insert(
                        1,
                        TutorSuggestion(
                            id="grammar_specific",
                            label="Explain my grammar note",
                            message=f"Explain this grammar mistake: {orig}",
                        ),
                    )
        except Exception:
            logger.debug("suggestions: context unavailable", exc_info=True)
    # Dedupe by id
    seen: set[str] = set()
    unique: list[TutorSuggestion] = []
    for s in items:
        if s.id in seen:
            continue
        seen.add(s.id)
        unique.append(s)
    return TutorSuggestionsResponse(suggestions=unique[:8])
