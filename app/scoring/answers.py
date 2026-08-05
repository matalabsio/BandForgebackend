"""Shared objective answer checking (Phase 3).

Contract for ``correct_answer``:
- Slash ``/`` separates **OR alternatives** (any one match wins), e.g. ``colour/color``, ``A/B``.
- Never treat comma or concatenated ``AB`` as OR-alts.
- Choose TWO exam items are **two question rows**, each with a single letter.
"""

from __future__ import annotations

from typing import Any


def normalize_answer(value: str | None) -> str:
    """Lowercase + strip + collapse whitespace for fair comparison."""
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def is_answer_correct(user_answer: str | None, correct_answer: str | None) -> bool:
    """Compare user input vs. stored correct answer (case-insensitive).

    Supports MCQ labels (A/B/C/D), TFNG (TRUE/FALSE/NOT GIVEN), and
    sentence-completion strings. Multi-answer cells separated by '/'
    are accepted as alternatives.
    """
    if correct_answer is None or correct_answer == "":
        return False
    user_norm = normalize_answer(user_answer)
    if not user_norm:
        return False
    alternatives = [normalize_answer(part) for part in str(correct_answer).split("/")]
    return user_norm in alternatives


def score_answers(
    *,
    questions: list[dict[str, Any]],
    answers_by_qid: dict[str, str],
) -> tuple[int, int, list[dict[str, Any]]]:
    """Score every question; return (raw, total, per_question_rows).

    ``per_question_rows`` is the list of upsert payloads for ``answers``
    (with ``is_correct`` set) — the service layer writes them to Supabase.
    """
    raw = 0
    total = len(questions)
    rows: list[dict[str, Any]] = []

    for q in questions:
        qid = str(q["id"])
        user = answers_by_qid.get(qid, "")
        correct = is_answer_correct(user, q.get("correct_answer"))
        if correct:
            raw += 1
        rows.append(
            {
                "question_id": qid,
                "user_answer": user,
                "is_correct": correct,
            }
        )
    return raw, total, rows


def build_skill_breakdown(
    *,
    questions: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, float | int]]:
    """Group correct/total by ``skill_tag``. Empty/None tag is bucketed as 'general'."""
    by_qid_correct = {str(r["question_id"]): bool(r.get("is_correct")) for r in rows}
    buckets: dict[str, dict[str, int]] = {}
    for q in questions:
        skill = (q.get("skill_tag") or "general").strip() or "general"
        bucket = buckets.setdefault(skill, {"correct": 0, "total": 0})
        bucket["total"] += 1
        if by_qid_correct.get(str(q["id"])):
            bucket["correct"] += 1

    output: dict[str, dict[str, float | int]] = {}
    for skill, b in buckets.items():
        total = b["total"]
        correct = b["correct"]
        pct = round(correct / total, 4) if total else 0.0
        output[skill] = {"correct": correct, "total": total, "pct": pct}
    return output
