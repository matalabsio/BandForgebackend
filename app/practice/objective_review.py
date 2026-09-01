"""Per-question review payloads for bank L/R practice exercises."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException, status

from app.listening.explanations import build_explanation
from app.scoring.answers import is_answer_correct

ObjectiveModule = Literal["listening", "reading"]


def _normalize_user_answer(given: Any) -> str:
    s = str(given).strip() if given is not None else ""
    if "::" in s:
        idx, rest = s.split("::", 1)
        if idx.isdigit():
            return rest.strip()
    return s


def build_objective_review_questions(
    qrows: list[dict[str, Any]],
    answers: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build ModuleReviewQuestion-compatible rows from bank questions + stored answers."""
    items: list[dict[str, Any]] = []
    sorted_rows = sorted(
        qrows,
        key=lambda row: int(row.get("question_number") or 0),
    )
    for q in sorted_rows:
        key = str(q["id"])
        expected = (q.get("correct_answer") or "").strip()
        if not expected:
            continue
        given_s = _normalize_user_answer(answers.get(key))
        correct_flag = is_answer_correct(given_s, expected)
        prompt = str(q.get("prompt") or "")
        stored_explanation = str(q.get("explanation") or "").strip()
        explanation = stored_explanation or build_explanation(
            prompt=prompt,
            user_answer=given_s,
            correct_answer=expected,
            is_correct=correct_flag,
        )
        items.append(
            {
                "question_id": key,
                "question_number": int(q.get("question_number") or 0),
                "question_type": str(q.get("question_type") or ""),
                "prompt": prompt,
                "user_answer": given_s,
                "correct_answer": expected,
                "is_correct": correct_flag,
                "explanation": explanation,
            }
        )
    return items


def get_practice_objective_review(
    *,
    user_id: UUID,
    hub_id: str,
    attempt_id: str,
    module: ObjectiveModule,
) -> dict[str, Any]:
    from app.db.supabase_client import get_supabase
    from app.practice.service import assert_hub_accessible

    flat = assert_hub_accessible(user_id=user_id, hub_id=hub_id)
    hub_skill = str(flat.get("skill") or "")
    if hub_skill != module:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"This hub is not a {module} exercise.",
        )

    sb = get_supabase()
    rows = (
        sb.table("practice_exercise_attempts")
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
    if attempt.get("status") != "completed":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Review is available after you submit the exercise.",
        )

    section_id = attempt.get("section_id")
    if not section_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="No section linked to this attempt.",
        )

    from app.cache.hybrid_cache import get_json, set_json

    cache_key = f"practice:section:{section_id}:questions:v2"
    qrows = get_json(cache_key)
    if not isinstance(qrows, list) or not qrows:
        qrows = (
            sb.table("bank_questions")
            .select(
                "id, correct_answer, question_type, prompt, options, question_number, explanation"
            )
            .eq("section_id", str(section_id))
            .execute()
        ).data or []
        if qrows:
            set_json(cache_key, qrows, 60)

    answers = attempt.get("answers")
    if not isinstance(answers, dict):
        answers = {}

    questions = build_objective_review_questions(qrows, answers)
    raw_score = sum(1 for q in questions if q["is_correct"])
    score = attempt.get("score") if isinstance(attempt.get("score"), dict) else {}
    total = int(score.get("total") or len(questions) or 0)

    return {
        "attempt_id": attempt_id,
        "hub_id": hub_id,
        "module": module,
        "raw_score": raw_score,
        "total_questions": total or len(questions),
        "questions": questions,
    }
