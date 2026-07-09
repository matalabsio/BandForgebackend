"""Module-complete answer review for full mock attempts.

After every part (listening) or passage (reading) of a module is submitted,
the student sees one review rolling up all questions with correct answers.
This module aggregates the already-scored answers across every completed
attempt in the module for a mock session. Nothing is re-graded destructively;
we reuse the stored `is_correct` flag and fall back to `is_answer_correct`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.config import get_settings
from app.listening import repository as listening_repo
from app.listening.evaluation import is_answer_correct as listening_is_correct
from app.listening.explanations import build_explanation as listening_explanation
from app.mock_catalog.constants import (
    M02_MOCK_TEST_ID,
    MODULE_LIVE_PARTS,
    live_content_part,
)
from app.reading import repository as reading_repo
from app.reading.evaluation import is_answer_correct as reading_is_correct
from app.schemas.mock_orchestrator import (
    ModuleReviewGroup,
    ModuleReviewQuestion,
    ModuleReviewResponse,
    SpeakingModuleReviewResponse,
    WritingModuleReviewResponse,
    WritingTaskReview,
)
from app.services import mock_orchestrator
from app.speaking import repository as speaking_repo
from app.speaking.ai_evaluator import ai_evaluation_available, run_speaking_evaluation
from app.writing import repository as writing_repo
from app.writing.ai_evaluator import ai_evaluation_available, evaluate_mock_essay

_READING_SECTION_LABELS: dict[str, str] = {
    "tfng": "True / False / Not Given",
    "matching_headings": "Matching Headings",
    "sentence_completion": "Sentence Completion",
}


def _is_dev() -> bool:
    return get_settings().app_env.strip().lower() == "development"


def _reading_section_label(*, mock_test_id: UUID, live_part: int, qtype: str) -> str:
    key = qtype.lower()
    if key == "tfng" and str(mock_test_id) == M02_MOCK_TEST_ID and live_part == 3:
        return "Yes / No / Not Given"
    return _READING_SECTION_LABELS.get(key, qtype.replace("_", " ").title())


def _reading_explanation(*, prompt: str, correct: str | None, ok: bool) -> str:
    if ok:
        return "Your answer matches the passage."
    if correct:
        return f"The passage supports: {correct}."
    return f"Review the passage for: {prompt[:120]}…"


def _live_parts(*, mock_test_id: UUID, module: str, completed_parts: list[int]) -> list[int]:
    configured = MODULE_LIVE_PARTS.get(str(mock_test_id), {}).get(module)
    if configured:
        return list(configured)
    return sorted(set(completed_parts))


def _completed_attempts_by_part(
    *, module_attempts: list[dict[str, Any]], module: str
) -> dict[int, dict[str, Any]]:
    by_part: dict[int, dict[str, Any]] = {}
    for attempt in module_attempts:
        if attempt.get("module") != module:
            continue
        if attempt.get("status") != "completed":
            continue
        part_raw = attempt.get("part")
        part = int(part_raw) if part_raw is not None else 1
        by_part[part] = attempt
    return by_part


def _answers_by_qid(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(row["question_id"]): {
            "user_answer": str(row.get("user_answer") or ""),
            "is_correct": row.get("is_correct"),
        }
        for row in rows
    }


def _listening_groups(
    *, mock_test_id: UUID, live_parts: list[int], attempts_by_part: dict[int, dict[str, Any]]
) -> list[ModuleReviewGroup]:
    offsets = listening_repo.part_display_offsets(mock_test_id=mock_test_id)
    groups: list[ModuleReviewGroup] = []
    for part in live_parts:
        attempt = attempts_by_part.get(part)
        if attempt is None:
            continue
        answers = _answers_by_qid(
            listening_repo.list_answers_for_attempt(UUID(str(attempt["id"])))
        )
        offset = offsets.get(part, 0)
        questions = listening_repo.list_questions_for_review(mock_test_id, part=part)
        items: list[ModuleReviewQuestion] = []
        raw = 0
        for q in questions:
            qid = str(q["id"])
            ans = answers.get(qid, {})
            user_answer = ans.get("user_answer", "")
            stored = ans.get("is_correct")
            ok = (
                bool(stored)
                if stored is not None
                else listening_is_correct(user_answer, q.get("correct_answer"))
            )
            if ok:
                raw += 1
            items.append(
                ModuleReviewQuestion(
                    question_id=UUID(qid),
                    question_number=offset + int(q["question_number"]),
                    question_type=str(q.get("question_type") or ""),
                    prompt=str(q.get("prompt") or ""),
                    user_answer=user_answer,
                    correct_answer=str(q.get("correct_answer") or "—"),
                    is_correct=ok,
                    explanation=listening_explanation(
                        prompt=str(q.get("prompt") or ""),
                        user_answer=user_answer,
                        correct_answer=q.get("correct_answer"),
                        is_correct=ok,
                    ),
                )
            )
        groups.append(
            ModuleReviewGroup(
                label=f"Part {part}",
                raw_score=raw,
                total_questions=len(items),
                questions=items,
            )
        )
    return groups


def _reading_groups(
    *, mock_test_id: UUID, live_parts: list[int], attempts_by_part: dict[int, dict[str, Any]]
) -> list[ModuleReviewGroup]:
    groups: list[ModuleReviewGroup] = []
    for live_part in live_parts:
        attempt = attempts_by_part.get(live_part)
        if attempt is None:
            continue
        content_part = live_content_part(
            mock_test_id=str(mock_test_id), module="reading", live_part=live_part
        )
        offset = reading_repo.display_offset_before_part(
            mock_test_id=mock_test_id, part=live_part
        )
        answers = _answers_by_qid(
            reading_repo.list_answers_for_attempt(UUID(str(attempt["id"])))
        )
        questions = reading_repo.list_questions_for_review(
            mock_test_id, part=content_part
        )
        # Group consecutive questions by question type (TFNG / headings / completion).
        section_order: list[str] = []
        section_items: dict[str, list[ModuleReviewQuestion]] = {}
        section_raw: dict[str, int] = {}
        for q in questions:
            qtype = str(q.get("question_type") or "").lower()
            if qtype not in section_items:
                section_order.append(qtype)
                section_items[qtype] = []
                section_raw[qtype] = 0
            qid = str(q["id"])
            ans = answers.get(qid, {})
            user_answer = ans.get("user_answer", "")
            stored = ans.get("is_correct")
            ok = (
                bool(stored)
                if stored is not None
                else reading_is_correct(user_answer, q.get("correct_answer"))
            )
            if ok:
                section_raw[qtype] += 1
            correct_display = str(q.get("correct_answer") or "—")
            section_items[qtype].append(
                ModuleReviewQuestion(
                    question_id=UUID(qid),
                    question_number=offset + int(q["question_number"]),
                    question_type=qtype,
                    prompt=str(q.get("prompt") or ""),
                    user_answer=user_answer,
                    correct_answer=correct_display,
                    is_correct=ok,
                    explanation=_reading_explanation(
                        prompt=str(q.get("prompt") or ""),
                        correct=q.get("correct_answer"),
                        ok=ok,
                    ),
                )
            )
        for qtype in section_order:
            section_label = _reading_section_label(
                mock_test_id=mock_test_id, live_part=live_part, qtype=qtype
            )
            groups.append(
                ModuleReviewGroup(
                    label=f"Passage {live_part} · {section_label}",
                    raw_score=section_raw[qtype],
                    total_questions=len(section_items[qtype]),
                    questions=section_items[qtype],
                )
            )
    return groups


def get_module_review(
    *,
    mock_attempt_id: UUID,
    module: str,
    user_id: UUID,
) -> ModuleReviewResponse:
    if module not in ("listening", "reading"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Module review is only available for listening and reading.",
        )

    (
        row,
        mock_test_id,
        modules,
        module_attempts,
        scores,
    ) = mock_orchestrator._load_mock_attempt_context(
        mock_attempt_id=mock_attempt_id, user_id=user_id
    )

    attempts_by_part = _completed_attempts_by_part(
        module_attempts=module_attempts, module=module
    )
    live_parts = _live_parts(
        mock_test_id=mock_test_id,
        module=module,
        completed_parts=list(attempts_by_part.keys()),
    )
    missing = [p for p in live_parts if p not in attempts_by_part]
    if missing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Finish every section of this module before viewing the review.",
        )

    if module == "listening":
        groups = _listening_groups(
            mock_test_id=mock_test_id,
            live_parts=live_parts,
            attempts_by_part=attempts_by_part,
        )
    else:
        groups = _reading_groups(
            mock_test_id=mock_test_id,
            live_parts=live_parts,
            attempts_by_part=attempts_by_part,
        )

    raw_total = sum(g.raw_score for g in groups)
    question_total = sum(g.total_questions for g in groups)

    progress = mock_orchestrator._progress_from_context(
        row=row,
        mock_test_id=mock_test_id,
        modules=modules,
        module_attempts=module_attempts,
        scores_by_attempt=scores,
        include_bands=False,
    )

    return ModuleReviewResponse(
        module=module,  # type: ignore[arg-type]
        mock_attempt_id=mock_attempt_id,
        raw_score=raw_total,
        total_questions=question_total,
        groups=groups,
        next_module=progress.next_module,
        next_part=progress.next_part,
    )


def _round_half(value: float) -> float:
    return round(value * 2) / 2


def _writing_persona(tasks: list[WritingTaskReview], ai_band: float | None) -> str:
    graded = [t for t in tasks if t.ai_band is not None]
    if not graded or ai_band is None:
        return (
            "Both writing tasks are submitted. A certified examiner will send your "
            "official band within 24–48 hours; open each task to review your response."
        )
    parts: list[str] = [
        f"Your AI-estimated Writing band across both tasks is about {ai_band:.1f}.",
    ]
    weakest_criterion: tuple[str, float] | None = None
    label_map = {
        "task_achievement": "Task Achievement",
        "coherence": "Coherence & Cohesion",
        "lexical_resource": "Lexical Resource",
        "grammar": "Grammar Range & Accuracy",
    }
    for task in graded:
        for key, score in task.criteria.items():
            if weakest_criterion is None or score < weakest_criterion[1]:
                weakest_criterion = (label_map.get(key, key), score)
    if weakest_criterion is not None:
        parts.append(
            f"Your lowest criterion is {weakest_criterion[0]} — focus there for the fastest gain.",
        )
    parts.append(
        "This is an estimate; your examiner band replaces it on the results page.",
    )
    return " ".join(parts)


async def get_writing_module_review(
    *, mock_attempt_id: UUID, user_id: UUID
) -> WritingModuleReviewResponse:
    (
        row,
        mock_test_id,
        modules,
        module_attempts,
        scores,
    ) = mock_orchestrator._load_mock_attempt_context(
        mock_attempt_id=mock_attempt_id, user_id=user_id
    )

    live_parts = _live_parts(
        mock_test_id=mock_test_id,
        module="writing",
        completed_parts=[],
    )
    attempts = writing_repo.list_completed_writing_attempts_for_session(
        user_id=user_id, mock_attempt_id=mock_attempt_id
    )
    by_part = {int(a.get("part") or 1): a for a in attempts}
    missing = [p for p in live_parts if p not in by_part]
    if missing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Finish both writing tasks before viewing the review.",
        )

    tasks: list[WritingTaskReview] = []
    ai_bands: list[float] = []
    for part in live_parts:
        attempt = by_part[part]
        attempt_id = UUID(str(attempt["id"]))
        review = writing_repo.get_writing_review_for_attempt(attempt_id) or {}
        meta = review.get("submission_meta") or {}
        ai_scores = review.get("ai_scores") or {}
        essay = str(meta.get("essay") or "")
        prompt = str(meta.get("question") or "")
        words = int(meta.get("word_count") or 0)

        ai_band = ai_scores.get("ai_band")
        criteria = ai_scores.get("criteria")
        if ai_band is None and essay:
            evaluation = await evaluate_mock_essay(part=part, question=prompt, essay=essay)
            if evaluation is not None:
                merged = {**ai_scores, **evaluation}
                review_id = review.get("id")
                if review_id:
                    writing_repo.update_writing_review_ai_scores(
                        review_id=UUID(str(review_id)), ai_scores=merged
                    )
                ai_band = evaluation.get("ai_band")
                criteria = evaluation.get("criteria")
                ai_scores = merged

        task = WritingTaskReview(
            attempt_id=attempt_id,
            part=part,
            prompt=prompt,
            essay=essay,
            word_count=words,
            ai_band=float(ai_band) if ai_band is not None else None,
            criteria={k: float(v) for k, v in (criteria or {}).items()},
            strengths=list(ai_scores.get("strengths") or []),
            improvements=list(ai_scores.get("improvements") or []),
        )
        if task.ai_band is not None:
            ai_bands.append(task.ai_band)
        tasks.append(task)

    module_ai_band = _round_half(sum(ai_bands) / len(ai_bands)) if ai_bands else None

    progress = mock_orchestrator._progress_from_context(
        row=row,
        mock_test_id=mock_test_id,
        modules=modules,
        module_attempts=module_attempts,
        scores_by_attempt=scores,
        include_bands=False,
    )

    return WritingModuleReviewResponse(
        mock_attempt_id=mock_attempt_id,
        tasks=tasks,
        ai_band=module_ai_band,
        persona_message=_writing_persona(tasks, module_ai_band),
        ai_available=ai_evaluation_available(),
        next_module=progress.next_module,
        next_part=progress.next_part,
    )


def _estimate_speaking_band(
    *, duration_sec: int | None, hint_sec: int | None
) -> float | None:
    """Very rough v1 estimate from how fully the candidate used the time."""
    if not duration_sec or duration_sec <= 0:
        return None
    target = hint_sec or 60
    ratio = min(1.0, duration_sec / target)
    # 30s of speech ≈ band 5, full time ≈ band 6.5 (placeholder until human review).
    band = 5.0 + ratio * 1.5
    return _round_half(band)


def _speaking_delivery_notes(
    *, duration_sec: int | None, hint_sec: int | None
) -> list[str]:
    notes: list[str] = []
    target = hint_sec or 60
    if not duration_sec:
        notes.append("We couldn't measure your speaking time on this recording.")
        return notes
    if duration_sec < target * 0.6:
        notes.append(
            f"You spoke for about {duration_sec}s of the ~{target}s available — aim to extend each answer.",
        )
    else:
        notes.append(
            f"You used about {duration_sec}s of the ~{target}s available — good use of time.",
        )
    return notes


def get_speaking_module_review(
    *, mock_attempt_id: UUID, user_id: UUID
) -> SpeakingModuleReviewResponse:
    (
        row,
        mock_test_id,
        modules,
        module_attempts,
        scores,
    ) = mock_orchestrator._load_mock_attempt_context(
        mock_attempt_id=mock_attempt_id, user_id=user_id
    )

    speaking_attempts = [
        a
        for a in module_attempts
        if a.get("module") == "speaking" and a.get("status") == "completed"
    ]
    if not speaking_attempts:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Submit your speaking recording before viewing the review.",
        )
    attempt = sorted(speaking_attempts, key=lambda a: int(a.get("part") or 1))[0]
    attempt_id = UUID(str(attempt["id"]))
    part = int(attempt.get("part") or 1)

    review = speaking_repo.get_speaking_review_for_attempt(attempt_id) or {}
    meta = review.get("submission_meta") or {}
    ai_scores = review.get("ai_scores") or {}
    duration_sec = meta.get("duration_sec")
    duration_sec = int(duration_sec) if duration_sec is not None else None

    questions = speaking_repo.list_questions_for_part(
        mock_test_id=mock_test_id, part=part
    )
    prompts = [str(q.get("prompt") or "") for q in questions if q.get("prompt")]
    hint_sec = None
    if questions:
        opts = questions[0].get("options")
        if isinstance(opts, dict) and opts.get("duration_hint_sec") is not None:
            hint_sec = int(opts["duration_hint_sec"])

    ai_band = ai_scores.get("ai_band")
    ai_status = ai_scores.get("status") if isinstance(ai_scores, dict) else None

    if ai_status in ("ai_complete", "ai_stub"):
        ai_band = ai_scores.get("ai_band")
    elif (
        review.get("id")
        and ai_status == "pending"
        and ai_evaluation_available()
    ):
        run_speaking_evaluation(UUID(str(review["id"])))
        review = speaking_repo.get_speaking_review_for_attempt(attempt_id) or {}
        ai_scores = review.get("ai_scores") or {}
        ai_band = ai_scores.get("ai_band")

    if ai_band is None:
        ai_band = _estimate_speaking_band(duration_sec=duration_sec, hint_sec=hint_sec)
        if ai_band is not None and review.get("id") and ai_status not in (
            "ai_complete",
            "ai_stub",
        ):
            merged = {**(ai_scores if isinstance(ai_scores, dict) else {}), "ai_band": ai_band}
            speaking_repo.update_speaking_review_ai_scores(
                review_id=UUID(str(review["id"])), ai_scores=merged
            )
    ai_band = float(ai_band) if ai_band is not None else None

    persona = (
        f"Your AI-estimated Speaking band is about {ai_band:.1f}. "
        "A certified examiner will confirm your official band within 24 hours."
        if ai_band is not None
        else (
            "Your recording is submitted. A certified examiner will send your "
            "official Speaking band within 24 hours."
        )
    )

    progress = mock_orchestrator._progress_from_context(
        row=row,
        mock_test_id=mock_test_id,
        modules=modules,
        module_attempts=module_attempts,
        scores_by_attempt=scores,
        include_bands=False,
    )

    return SpeakingModuleReviewResponse(
        mock_attempt_id=mock_attempt_id,
        attempt_id=attempt_id,
        part=part,
        duration_seconds=duration_sec,
        duration_hint_seconds=hint_sec,
        ai_band=ai_band,
        prompts=prompts,
        delivery_notes=_speaking_delivery_notes(
            duration_sec=duration_sec, hint_sec=hint_sec
        ),
        persona_message=persona,
        next_module=progress.next_module,
        next_part=progress.next_part,
    )
