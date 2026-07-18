"""Build tutoring context from essay, evaluation, history, and learning profile."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.db.supabase_client import execute_with_retry, get_supabase
from app.learning.service import fetch_profile_row
from app.writing import repository as repo
from app.writing.service import get_review


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _trim_essay(essay: str, *, max_chars: int = 3500) -> str:
    text = essay.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _review_snapshot(review: Any) -> dict[str, Any]:
    grammar = [
        {
            "original": getattr(m, "original", None) or (m.get("original") if isinstance(m, dict) else None),
            "correction": getattr(m, "correction", None)
            or (m.get("correction") if isinstance(m, dict) else None),
            "issue": getattr(m, "issue", None) or (m.get("issue") if isinstance(m, dict) else None),
        }
        for m in (review.grammar_mistakes or [])[:8]
    ]
    vocab = []
    for v in review.vocabulary_highlights or []:
        if hasattr(v, "model_dump"):
            item = v.model_dump()
        elif isinstance(v, dict):
            item = v
        else:
            continue
        polarity = str(item.get("polarity") or "").lower()
        if polarity == "weak" or not polarity:
            vocab.append(
                {
                    "word": item.get("word"),
                    "polarity": polarity or "weak",
                    "alternatives": list(item.get("alternatives") or [])[:4],
                }
            )
        if len(vocab) >= 8:
            break

    band = review.band if review.band is not None else review.ai_band
    return {
        "attempt_id": str(review.attempt_id),
        "part": review.part,
        "prompt": (review.prompt or "")[:800],
        "essay": _trim_essay(review.user_answer or ""),
        "word_count": review.word_count,
        "band": band,
        "ai_band": review.ai_band,
        "band_source": review.band_source,
        "criteria": dict(review.ai_criteria or {}),
        "strengths": list(review.ai_strengths or [])[:6],
        "improvements": list(review.ai_improvements or [])[:6],
        "grammar_mistakes": grammar,
        "vocabulary_weak": vocab,
        "next_band_advice": (review.next_band_advice or "")[:600],
        "strong_spans": [
            (s.text if hasattr(s, "text") else s.get("text"))
            for s in (review.strong_spans or [])[:5]
            if (hasattr(s, "text") and s.text) or (isinstance(s, dict) and s.get("text"))
        ],
    }


def _prior_writing_summaries(user_id: UUID, *, exclude_attempt_id: UUID, limit: int = 2) -> list[dict[str, Any]]:
    client = get_supabase()
    attempts = execute_with_retry(
        lambda: (
            client.table("test_attempts")
            .select("id, completed_at")
            .eq("user_id", str(user_id))
            .eq("module", "writing")
            .eq("status", "completed")
            .neq("id", str(exclude_attempt_id))
            .order("completed_at", desc=True)
            .limit(limit)
            .execute()
        )
    ).data or []
    out: list[dict[str, Any]] = []
    for row in attempts:
        aid = UUID(str(row["id"]))
        try:
            review = get_review(attempt_id=aid, user_id=user_id)
        except Exception:
            continue
        snap = _review_snapshot(review)
        out.append(
            {
                "attempt_id": snap["attempt_id"],
                "band": snap["band"],
                "criteria": snap["criteria"],
                "improvements": snap["improvements"][:2],
            }
        )
    return out


def _profile_slim(user_id: UUID) -> dict[str, Any]:
    row = fetch_profile_row(user_id)
    if not row:
        return {}
    return {
        "target_band": _safe_float(row.get("target_band")),
        "current_band": _safe_float(row.get("current_band")),
        "top_weaknesses": list(row.get("top_weaknesses") or [])[:5],
        "grammar_stats": row.get("grammar_stats") or {},
        "vocab_stats": row.get("vocab_stats") or {},
        "module_summary_writing": (row.get("module_summary") or {}).get("writing"),
    }


def build_context_pack(*, attempt_id: UUID, user_id: UUID) -> dict[str, Any]:
    """Load authoritative tutoring context for an owned writing attempt."""
    attempt = repo.get_attempt(attempt_id)
    from app.security.ownership import ensure_owner_or_not_found

    ensure_owner_or_not_found(attempt, user_id)
    if attempt.get("module") != "writing":
        from fastapi import HTTPException, status

        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not a writing attempt.")

    review = get_review(attempt_id=attempt_id, user_id=user_id)
    current = _review_snapshot(review)
    prior = _prior_writing_summaries(user_id, exclude_attempt_id=attempt_id, limit=2)
    profile = _profile_slim(user_id)

    return {
        "current": current,
        "prior_attempts": prior,
        "learning_profile": profile,
    }


def used_context_summary(pack: dict[str, Any]) -> dict[str, Any]:
    current = pack.get("current") or {}
    profile = pack.get("learning_profile") or {}
    return {
        "attempt_id": str(current.get("attempt_id") or ""),
        "band": current.get("band"),
        "has_essay": bool((current.get("essay") or "").strip()),
        "grammar_count": len(current.get("grammar_mistakes") or []),
        "vocab_weak_count": len(current.get("vocabulary_weak") or []),
        "prior_attempts": len(pack.get("prior_attempts") or []),
        "profile_weaknesses": len(profile.get("top_weaknesses") or []),
    }
