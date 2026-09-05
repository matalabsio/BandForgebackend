"""Production AI evaluation for Question Bank writing practice exercises.

Reuses evaluate_writing_essay (v5 system prompt) — same engine as mock / diagnostic.
Stores the AI payload on practice_exercise_attempts.score (kind=writing_ai).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, status

from app.diagnostic.writing_prompt import resolve_prompt_version
from app.writing.ai_evaluator import (
    AI_STATUS_COMPLETE,
    AI_STATUS_FAILED,
    AI_STATUS_PENDING,
    AI_STATUS_STUB,
    ai_evaluation_available,
    evaluate_mock_essay,
)
from app.writing.eval_utils import MIN_WORDS_FOR_AI, sanitize_essay, word_count
from app.writing.evaluation import calculate_writing_band, min_words_for_part

logger = logging.getLogger(__name__)

SCORE_KIND = "writing_ai"


def resolve_ielts_writing_part(
    *,
    question_type: str = "",
    section_part: int | None = None,
    title: str | None = None,
) -> int:
    """Map bank metadata → IELTS Task 1 or 2.

    bank_sections.part is often always 1 for writing hubs; prefer question_type.
    """
    qtype = (question_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    if qtype:
        if "task2" in qtype or qtype in ("task_2", "t2"):
            return 2
        if "task1" in qtype or qtype in ("task_1", "t1"):
            return 1

    title_s = (title or "").strip().lower()
    if title_s:
        if (
            "_t2" in title_s
            or title_s.endswith("t2")
            or "task 2" in title_s
            or "task2" in title_s
            or "wt_t2" in title_s
        ):
            return 2
        if (
            "_t1" in title_s
            or title_s.endswith("t1")
            or "task 1" in title_s
            or "task1" in title_s
            or "wt_t1" in title_s
        ):
            return 1

    if section_part is not None:
        try:
            sp = int(section_part)
        except (TypeError, ValueError):
            sp = 1
        if sp >= 2:
            return 2
    return 1


def _sb():
    from app.db.supabase_client import get_supabase

    return get_supabase()


def _update_attempt_score(attempt_id: str, score: dict[str, Any]) -> None:
    _sb().table("practice_exercise_attempts").update({"score": score}).eq(
        "id", attempt_id
    ).execute()


def build_pending_writing_score(
    *,
    part: int,
    question: str,
    essay: str,
    visual_description: str = "",
    test_title: str | None = None,
    question_type: str = "writing",
) -> dict[str, Any]:
    cleaned = sanitize_essay(essay, question)
    words = word_count(cleaned)
    return {
        "kind": SCORE_KIND,
        "status": AI_STATUS_PENDING,
        "part": part,
        "question": question,
        "essay": cleaned or essay.strip(),
        "visual_description": (visual_description or "").strip(),
        "test_title": test_title,
        "question_type": question_type,
        "word_count": words,
        "word_count_estimate": calculate_writing_band(words=words, part=part),
        "min_words": min_words_for_part(part),
        "prompt_version": resolve_prompt_version(),
        "queued_at": datetime.now(UTC).isoformat(),
    }


async def _evaluate_practice_writing_async(attempt_id: str) -> None:
    sb = _sb()
    rows = (
        sb.table("practice_exercise_attempts")
        .select("id, score, status")
        .eq("id", attempt_id)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        logger.warning("Practice writing attempt %s not found for AI eval", attempt_id)
        return

    score = rows[0].get("score")
    if not isinstance(score, dict) or score.get("kind") != SCORE_KIND:
        return
    if score.get("status") in (AI_STATUS_COMPLETE, AI_STATUS_STUB):
        return

    part = int(score.get("part") or 1)
    question = str(score.get("question") or "")
    essay = str(score.get("essay") or "").strip()
    visual = str(score.get("visual_description") or "").strip()
    words = int(score.get("word_count") or word_count(essay))

    if words < MIN_WORDS_FOR_AI or not essay:
        failed = {
            **score,
            "status": AI_STATUS_FAILED,
            "error": "Response too short for IELTS AI evaluation.",
            "word_count": words,
            "short_response": True,
            "completed_at": datetime.now(UTC).isoformat(),
        }
        _update_attempt_score(attempt_id, failed)
        return

    if not ai_evaluation_available():
        failed = {
            **score,
            "status": AI_STATUS_FAILED,
            "error": "Writing AI evaluation is not configured.",
            "completed_at": datetime.now(UTC).isoformat(),
        }
        _update_attempt_score(attempt_id, failed)
        return

    try:
        ai_scores = await evaluate_mock_essay(
            part=part,
            question=question,
            essay=essay,
            visual_description=visual or None,
        )
        if not ai_scores:
            raise RuntimeError("Writing AI returned no result")
        from app.config import get_settings

        status_val = (
            AI_STATUS_STUB if get_settings().writing_eval_stub else AI_STATUS_COMPLETE
        )
        merged = {
            **score,
            **ai_scores,
            "status": status_val,
            "error": None,
            "completed_at": datetime.now(UTC).isoformat(),
        }
        _update_attempt_score(attempt_id, merged)
        logger.info(
            "Practice writing AI complete (attempt=%s, band=%s, provider=%s)",
            attempt_id,
            ai_scores.get("ai_band"),
            ai_scores.get("provider_used"),
        )
    except Exception as exc:
        logger.exception("Practice writing AI failed (attempt=%s)", attempt_id)
        failed = {
            **score,
            "status": AI_STATUS_FAILED,
            "error": str(exc) or "AI evaluation failed.",
            "completed_at": datetime.now(UTC).isoformat(),
        }
        _update_attempt_score(attempt_id, failed)


def run_practice_writing_evaluation(attempt_id: str) -> None:
    """Sync entry for FastAPI BackgroundTasks; never raises to callers."""
    try:
        asyncio.run(_evaluate_practice_writing_async(attempt_id))
    except Exception:
        logger.exception(
            "run_practice_writing_evaluation failed for attempt %s", attempt_id
        )


def enqueue_practice_writing_eval(
    *,
    attempt_id: str,
    background_tasks: BackgroundTasks | None,
) -> None:
    if background_tasks is not None:
        background_tasks.add_task(run_practice_writing_evaluation, attempt_id)
    else:
        run_practice_writing_evaluation(attempt_id)


def extract_writing_essay_from_answers(
    answers: dict[str, Any],
    questions: list[dict[str, Any]],
) -> tuple[str, str, str, str]:
    """Return (essay, question_prompt, question_type, visual_description)."""
    if not questions:
        for val in answers.values():
            text = str(val or "").strip()
            if text:
                return text, "", "writing", ""
        return "", "", "writing", ""

    q = questions[0]
    qid = str(q.get("id") or "")
    essay = str(answers.get(qid) or "").strip()
    if not essay:
        for val in answers.values():
            text = str(val or "").strip()
            if text:
                essay = text
                break
    prompt = str(q.get("prompt") or "").strip()
    qtype = str(q.get("question_type") or "writing").strip() or "writing"
    opts = q.get("options") if isinstance(q.get("options"), dict) else {}
    visual = ""
    if isinstance(opts, dict):
        visual = str(
            opts.get("figure_note")
            or opts.get("visual_description")
            or opts.get("chart_description")
            or ""
        ).strip()
    return essay, prompt, qtype, visual


def get_practice_writing_review(
    *,
    user_id: UUID,
    hub_id: str,
    attempt_id: str,
) -> dict[str, Any]:
    """Public review payload compatible with WritingFeedbackView mapping."""
    rows = (
        _sb()
        .table("practice_exercise_attempts")
        .select("*")
        .eq("id", attempt_id)
        .eq("user_id", str(user_id))
        .eq("hub_id", str(hub_id))
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Attempt not found")

    attempt = rows[0]
    score = attempt.get("score") if isinstance(attempt.get("score"), dict) else {}
    if score.get("kind") != SCORE_KIND:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This attempt has no writing AI evaluation.",
        )

    part = int(score.get("part") or attempt.get("part") or 1)
    ai_status = str(score.get("status") or AI_STATUS_PENDING)
    ai_band = score.get("ai_band")
    try:
        ai_band_f = float(ai_band) if ai_band is not None else None
    except (TypeError, ValueError):
        ai_band_f = None

    criteria = score.get("criteria") if isinstance(score.get("criteria"), dict) else {}
    return {
        "attempt_id": attempt_id,
        "hub_id": hub_id,
        "status": str(attempt.get("status") or "completed"),
        "module": "writing",
        "part": part,
        "test_title": score.get("test_title") or f"Writing Task {part} practice",
        "question_type": str(score.get("question_type") or "writing"),
        "prompt": str(score.get("question") or ""),
        "options": None,
        "user_answer": str(score.get("essay") or ""),
        "word_count": int(score.get("word_count") or 0),
        "band": ai_band_f,
        "ai_band": ai_band_f,
        "ai_available": ai_evaluation_available(),
        "ai_status": ai_status,
        "band_source": "ai" if ai_band_f is not None else "none",
        "human_verified": False,
        "reviewer_notes": None,
        "ai_criteria": {
            str(k): float(v)
            for k, v in criteria.items()
            if isinstance(v, (int, float))
        },
        "ai_strengths": [str(x) for x in (score.get("strengths") or [])],
        "ai_improvements": [str(x) for x in (score.get("improvements") or [])],
        "ai_model_name": score.get("model_name"),
        "ai_provider": score.get("provider_used"),
        "spelling_mistakes": score.get("spelling_mistakes") or [],
        "grammar_mistakes": score.get("grammar_mistakes") or [],
        "next_band_advice": str(score.get("next_band_advice") or ""),
        "confidence": score.get("confidence"),
        "vocabulary_highlights": score.get("vocabulary_highlights") or [],
        "strong_spans": score.get("strong_spans") or [],
        "min_words": int(score.get("min_words") or min_words_for_part(part)),
        "submitted_at": attempt.get("completed_at"),
        "saved_for_review": True,
        "error": score.get("error"),
        "word_count_estimate": score.get("word_count_estimate"),
        "short_response": bool(score.get("short_response"))
        or (
            ai_status == AI_STATUS_FAILED
            and (
                "too short" in str(score.get("error") or "").lower()
                or int(score.get("word_count") or 0) < MIN_WORDS_FOR_AI
            )
        ),
    }
