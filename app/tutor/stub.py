"""Deterministic stub tutor — quotes student band/mistakes (non-generic)."""

from __future__ import annotations

import json
import re
from typing import Any


def _intent(message: str) -> str:
    m = message.lower()
    if any(k in m for k in ("band 8", "band8", "higher band", "model answer")):
        return "band8"
    if any(k in m for k in ("rewrite", "rephrase", "revise")):
        return "rewrite"
    if any(k in m for k in ("vocab", "vocabulary", "lexic", "stronger word")):
        return "vocab"
    if any(k in m for k in ("coheren", "cohesion", "paragraph structure")):
        return "coherence"
    if any(k in m for k in ("grammar", "mistake", "error", "tense", "article")):
        return "grammar"
    if any(k in m for k in ("why", "band", "score", "criteria")):
        return "why_band"
    return "general"


def stub_tutor_reply(
    *,
    context_pack: dict[str, Any],
    message: str,
    selection: str | None = None,
) -> dict[str, Any]:
    current = context_pack.get("current") or {}
    band = current.get("band")
    criteria = current.get("criteria") or {}
    improvements = list(current.get("improvements") or [])
    grammar = list(current.get("grammar_mistakes") or [])
    vocab = list(current.get("vocabulary_weak") or [])
    essay = (current.get("essay") or "").strip()
    target = (context_pack.get("learning_profile") or {}).get("target_band")

    band_label = f"{float(band):.1f}" if band is not None else "n/a"
    intent = _intent(message)

    if intent == "why_band":
        crit_bits = ", ".join(f"{k.replace('_', ' ')} {float(v):.1f}" for k, v in list(criteria.items())[:4])
        tip = improvements[0] if improvements else "Develop ideas more fully with clearer examples."
        reply = (
            f"You received Band {band_label} on this essay because your criterion scores were "
            f"{crit_bits or 'not yet available'}. "
            f"The top improvement from your report: {tip} "
        )
        if target is not None:
            reply += f"Your target is Band {float(target):.1f} — close the gap on the weakest criterion first."
        focus = "why_band"

    elif intent == "grammar":
        mist = None
        if selection:
            for g in grammar:
                orig = str(g.get("original") or "")
                if orig and orig.lower() in selection.lower():
                    mist = g
                    break
        if mist is None and grammar:
            mist = grammar[0]
        if mist:
            reply = (
                f"Looking at your grammar note: “{mist.get('original')}” → “{mist.get('correction')}” "
                f"(issue: {mist.get('issue') or 'grammar'}). "
                f"In Band {band_label} writing, fix this pattern consistently across the essay — "
                f"one-off corrections rarely move the grammar criterion."
            )
        else:
            reply = (
                f"Your Band {band_label} report does not list a matching grammar mistake for that ask. "
                f"Share a sentence from your essay and I will explain it against your criteria."
            )
        focus = "grammar"

    elif intent == "rewrite":
        excerpt = (selection or "").strip() or _last_paragraph(essay)
        rewritten = _simple_upgrade(excerpt) if excerpt else ""
        reply = (
            f"Here is a clearer rewrite of your text for Band {band_label} feedback:\n\n"
            f"{rewritten or '(no essay text available)'}\n\n"
            f"I kept your meaning but tightened cohesion"
            + (f" — linked to: {improvements[0]}" if improvements else ".")
        )
        focus = "rewrite"

    elif intent == "band8":
        excerpt = (selection or "").strip() or essay[:600]
        reply = (
            f"A Band 8-oriented version of your material (from your Band {band_label} draft):\n\n"
            f"{_simple_upgrade(excerpt) if excerpt else '(essay missing)'}\n\n"
            "Band 8 usually needs precise vocabulary, controlled complex sentences, and fully extended ideas — "
            f"your report highlights: {(improvements[0] if improvements else 'see criteria gaps')}."
        )
        focus = "band8"

    elif intent == "vocab":
        if vocab:
            bits = []
            for v in vocab[:3]:
                alts = ", ".join(str(a) for a in (v.get("alternatives") or [])[:3]) or "more precise academic synonyms"
                bits.append(f"“{v.get('word')}” → try {alts}")
            reply = (
                f"Stronger vocabulary for this essay (from your weak highlights at Band {band_label}): "
                + "; ".join(bits)
                + "."
            )
        else:
            reply = (
                f"No weak vocabulary highlights are stored for this Band {band_label} attempt yet. "
                "Select a basic word in your essay and ask again."
            )
        focus = "vocab"

    elif intent == "coherence":
        coh = criteria.get("coherence") or criteria.get("coherence_cohesion")
        reply = (
            f"Coherence on this attempt sits at "
            f"{f'{float(coh):.1f}' if coh is not None else 'an unknown score'} "
            f"(overall Band {band_label}). "
        )
        if improvements:
            reply += f"Your feedback points to: {improvements[0]} "
        reply += (
            "Use clearer topic sentences and logical progression between paragraphs — "
            "grounded in this essay’s structure, not generic linking advice."
        )
        focus = "coherence"

    else:
        reply = (
            f"On this essay you scored Band {band_label}. "
            f"Ask about your band, a grammar mistake, a rewrite, a Band 8 version, vocabulary, or coherence — "
            f"I will use your score report"
            + (f" and note: {improvements[0]}" if improvements else ".")
        )
        focus = "general"

    return {"reply": reply, "focus": focus}


def _last_paragraph(essay: str) -> str:
    parts = [p.strip() for p in re.split(r"\n\s*\n", essay) if p.strip()]
    if parts:
        return parts[-1][:800]
    return essay[:800]


def _simple_upgrade(text: str) -> str:
    t = text.strip()
    if not t:
        return t
    # Light deterministic polish for stub demos — still clearly based on their text
    t = re.sub(r"\bvery important\b", "critical", t, flags=re.I)
    t = re.sub(r"\ba lot of\b", "numerous", t, flags=re.I)
    t = re.sub(r"\bgood\b", "effective", t, flags=re.I)
    if not t.endswith((".", "!", "?")):
        t += "."
    return t


def stub_tutor_chat_json(
    *,
    context_pack: dict[str, Any],
    message: str,
    selection: str | None,
) -> tuple[str, dict[str, Any]]:
    payload = stub_tutor_reply(
        context_pack=context_pack, message=message, selection=selection
    )
    content = json.dumps(payload)
    return content, {"stub": True, "content": content}
