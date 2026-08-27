"""Production AI evaluation for Question Bank speaking practice exercises.

Creates a real speaking test_attempt (manifest from bank_questions), reuses
upload/ASR/finalize + run_speaking_evaluation. Stores linkage on
practice_exercise_attempts.score (kind=speaking_ai).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, status

from app.speaking.ai_evaluator import (
    ai_evaluation_available,
    run_speaking_evaluation,
)
from app.speaking.speaking_prompt import PROMPT_VERSION

logger = logging.getLogger(__name__)

SCORE_KIND = "speaking_ai"
AI_STATUS_PENDING = "pending"
AI_STATUS_COMPLETE = "ai_complete"
AI_STATUS_STUB = "ai_stub"
AI_STATUS_FAILED = "ai_failed"

# FK anchor for practice bank speaking attempts (M01 has speaking content).
PRACTICE_SPEAKING_MOCK_TEST_ID = UUID("a0000000-0000-4000-8000-000000000001")


def _sb():
    from app.db.supabase_client import get_supabase

    return get_supabase()


def resolve_speaking_part(
    *,
    question_type: str = "",
    section_part: int | None = None,
    title: str | None = None,
) -> int:
    """Map bank metadata → IELTS Speaking part 1–3."""
    qtype = (question_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    if (
        "part3" in qtype
        or "part_3" in qtype
        or qtype in ("speaking_part3", "speaking_part_3", "p3")
    ):
        return 3
    if (
        "part2" in qtype
        or "part_2" in qtype
        or qtype in ("speaking_part2", "speaking_part_2", "p2")
    ):
        return 2
    if (
        "part1" in qtype
        or "part_1" in qtype
        or qtype in ("speaking_part1", "speaking_part_1", "p1")
    ):
        return 1

    title_s = (title or "").strip().lower()
    if title_s:
        if "_p3" in title_s or title_s.endswith("p3") or "part 3" in title_s:
            return 3
        if "_p2" in title_s or title_s.endswith("p2") or "part 2" in title_s:
            return 2
        if "_p1" in title_s or title_s.endswith("p1") or "part 1" in title_s:
            return 1

    if section_part is not None:
        try:
            sp = int(section_part)
        except (TypeError, ValueError):
            sp = 1
        if sp in (1, 2, 3):
            return sp
    return 1


def _bank_rows_to_question_rows(
    *,
    questions: list[dict[str, Any]],
    section_part: int,
    hub_title: str | None,
) -> list[dict[str, Any]]:
    """Shape bank_questions like `questions` rows for speaking manifest freeze."""
    rows: list[dict[str, Any]] = []
    for q in questions:
        qtype = str(q.get("question_type") or "speaking_part1")
        part = resolve_speaking_part(
            question_type=qtype,
            section_part=section_part,
            title=hub_title,
        )
        opts = q.get("options") if isinstance(q.get("options"), dict) else {}
        options = dict(opts) if isinstance(opts, dict) else {}
        rows.append(
            {
                "id": str(q["id"]),
                "prompt": str(q.get("prompt") or ""),
                "question_number": int(q.get("question_number") or 1),
                "question_type": qtype,
                "part": part,
                "options": options,
            }
        )
    return rows


def bootstrap_practice_speaking_attempt(
    *,
    user_id: UUID,
    practice_attempt_id: str,
    questions: list[dict[str, Any]],
    section_part: int,
    hub_title: str | None = None,
) -> dict[str, Any]:
    """Create linked speaking test_attempt with frozen bank manifest.

    Returns speaking_attempt_id, speaking_manifest_hash, and pending score blob.
    """
    if not questions:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Bank section has no speaking questions.",
        )

    from app.speaking import repository as speaking_repo
    from app.speaking.service import (
        _build_manifest,
        _freeze_manifest_from_rows,
        _manifest_payload,
    )

    rows = _bank_rows_to_question_rows(
        questions=questions,
        section_part=section_part,
        hub_title=hub_title,
    )
    _, digest = _build_manifest(rows)
    frozen = _freeze_manifest_from_rows(rows)
    payload = _manifest_payload(frozen)

    speaking_row = speaking_repo.insert_speaking_attempt(
        user_id=user_id,
        mock_test_id=PRACTICE_SPEAKING_MOCK_TEST_ID,
        part=1,
        speaking_manifest=payload,
        speaking_manifest_hash=digest,
    )
    speaking_attempt_id = str(speaking_row["id"])

    score = {
        "kind": SCORE_KIND,
        "status": AI_STATUS_PENDING,
        "speaking_attempt_id": speaking_attempt_id,
        "speaking_manifest_hash": digest,
        "prompt_version": PROMPT_VERSION,
        "hub_title": hub_title,
        "queued_at": datetime.now(UTC).isoformat(),
    }
    _sb().table("practice_exercise_attempts").update({"score": score}).eq(
        "id", practice_attempt_id
    ).execute()

    return {
        "speaking_attempt_id": speaking_attempt_id,
        "speaking_manifest_hash": digest,
        "score": score,
    }


def build_pending_speaking_score(
    *,
    speaking_attempt_id: str,
    speaking_manifest_hash: str,
    speaking_review_id: str | None = None,
    hub_title: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": SCORE_KIND,
        "status": AI_STATUS_PENDING,
        "speaking_attempt_id": speaking_attempt_id,
        "speaking_manifest_hash": speaking_manifest_hash,
        "speaking_review_id": speaking_review_id,
        "hub_title": hub_title,
        "prompt_version": PROMPT_VERSION,
        "queued_at": datetime.now(UTC).isoformat(),
    }


def _sync_score_from_review(
    practice_attempt_id: str,
    score: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    ai_scores = (
        review.get("ai_scores") if isinstance(review.get("ai_scores"), dict) else {}
    )
    ai_status = str(ai_scores.get("status") or AI_STATUS_PENDING)
    evaluation = (
        ai_scores.get("evaluation")
        if isinstance(ai_scores.get("evaluation"), dict)
        else {}
    )
    merged = {
        **score,
        "speaking_review_id": str(
            review.get("id") or score.get("speaking_review_id") or ""
        ),
        "status": ai_status
        if ai_status in (AI_STATUS_COMPLETE, AI_STATUS_STUB, AI_STATUS_FAILED)
        else AI_STATUS_PENDING,
        "ai_band": ai_scores.get("ai_band"),
        "fluency": ai_scores.get("fluency"),
        "lexical": ai_scores.get("lexical"),
        "grammar": ai_scores.get("grammar"),
        "pronunciation": ai_scores.get("pronunciation"),
        "provider_eval": ai_scores.get("provider_eval"),
        "model_eval": ai_scores.get("model_eval"),
        "evaluation": evaluation,
        "attempt_metrics": ai_scores.get("attempt_metrics")
        or ai_scores.get("fluency_metrics"),
        "part_metrics": ai_scores.get("part_metrics"),
        "error": ai_scores.get("error"),
        "synced_at": datetime.now(UTC).isoformat(),
    }
    if merged["status"] in (AI_STATUS_COMPLETE, AI_STATUS_STUB, AI_STATUS_FAILED):
        merged["completed_at"] = datetime.now(UTC).isoformat()
    _sb().table("practice_exercise_attempts").update({"score": merged}).eq(
        "id", practice_attempt_id
    ).execute()
    return merged


def enqueue_practice_speaking_eval(
    *,
    speaking_review_id: str,
    background_tasks: BackgroundTasks | None,
) -> None:
    review_uuid = UUID(str(speaking_review_id))
    if background_tasks is not None:
        background_tasks.add_task(run_speaking_evaluation, review_uuid)
    else:
        run_speaking_evaluation(review_uuid)


def finalize_practice_speaking_submit(
    *,
    user_id: UUID,
    practice_attempt_id: str,
    speaking_attempt_id: str,
    speaking_manifest_hash: str,
    hub_title: str | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    """After client finalize: link review, ensure eval is queued, return pending score."""
    from app.speaking import repository as speaking_repo
    from app.speaking.service import finalize_attempt

    attempt = speaking_repo.get_attempt(UUID(speaking_attempt_id))
    if not attempt or str(attempt.get("user_id")) != str(user_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Speaking attempt not found."
        )

    review = speaking_repo.get_speaking_review_for_attempt(UUID(speaking_attempt_id))
    if review is None:
        try:
            finalize_attempt(
                attempt_id=UUID(speaking_attempt_id),
                user_id=user_id,
                manifest_hash=speaking_manifest_hash
                or str(attempt.get("speaking_manifest_hash") or ""),
                background_tasks=background_tasks,
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Practice speaking finalize failed")
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"Speaking finalize failed: {exc}",
            ) from exc
        review = speaking_repo.get_speaking_review_for_attempt(
            UUID(speaking_attempt_id)
        )

    if review is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Speaking review is not ready. Finish recording and submit again.",
        )

    score = build_pending_speaking_score(
        speaking_attempt_id=speaking_attempt_id,
        speaking_manifest_hash=speaking_manifest_hash
        or str(attempt.get("speaking_manifest_hash") or ""),
        speaking_review_id=str(review["id"]),
        hub_title=hub_title,
    )
    ai_scores = (
        review.get("ai_scores") if isinstance(review.get("ai_scores"), dict) else {}
    )
    if ai_scores.get("status") in (
        AI_STATUS_COMPLETE,
        AI_STATUS_STUB,
        AI_STATUS_FAILED,
    ):
        score = _sync_score_from_review(practice_attempt_id, score, review)
    else:
        eval_status = str(review.get("evaluation_status") or "not_queued")
        if eval_status in ("not_queued", "failed", "retry_wait"):
            enqueue_practice_speaking_eval(
                speaking_review_id=str(review["id"]),
                background_tasks=background_tasks,
            )
        _sb().table("practice_exercise_attempts").update({"score": score}).eq(
            "id", practice_attempt_id
        ).execute()

    return score


def get_practice_speaking_review(
    *,
    user_id: UUID,
    hub_id: str,
    attempt_id: str,
) -> dict[str, Any]:
    """Public review payload for practice speaking results (provisional AI)."""
    from app.speaking import repository as speaking_repo

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
            detail="This attempt has no speaking AI evaluation.",
        )

    speaking_attempt_id = str(score.get("speaking_attempt_id") or "").strip()
    review = None
    if speaking_attempt_id:
        review = speaking_repo.get_speaking_review_for_attempt(
            UUID(speaking_attempt_id)
        )
        if review:
            score = _sync_score_from_review(attempt_id, score, review)

    ai_status = str(score.get("status") or AI_STATUS_PENDING)
    ai_band = score.get("ai_band")
    try:
        ai_band_f = float(ai_band) if ai_band is not None else None
    except (TypeError, ValueError):
        ai_band_f = None

    evaluation = (
        score.get("evaluation") if isinstance(score.get("evaluation"), dict) else {}
    )
    criteria = {
        "fluency": score.get("fluency"),
        "lexical": score.get("lexical"),
        "grammar": score.get("grammar"),
        "pronunciation": score.get("pronunciation"),
    }
    band_scores = (
        evaluation.get("band_scores")
        if isinstance(evaluation.get("band_scores"), dict)
        else {}
    )
    if criteria["fluency"] is None and band_scores.get("FC") is not None:
        criteria["fluency"] = band_scores.get("FC")
    if criteria["lexical"] is None and band_scores.get("LR") is not None:
        criteria["lexical"] = band_scores.get("LR")
    if criteria["grammar"] is None and band_scores.get("GRA") is not None:
        criteria["grammar"] = band_scores.get("GRA")
    if criteria["pronunciation"] is None and band_scores.get("P") is not None:
        criteria["pronunciation"] = band_scores.get("P")
    if ai_band_f is None and band_scores.get("overall") is not None:
        try:
            ai_band_f = float(band_scores["overall"])
        except (TypeError, ValueError):
            ai_band_f = None

    strengths = [str(x) for x in (evaluation.get("strengths") or []) if str(x).strip()]
    improvements = [
        str(x) for x in (evaluation.get("improvements") or []) if str(x).strip()
    ]
    next_advice = str(evaluation.get("next_band_advice") or "").strip() or None
    evidence = [
        item
        for item in (evaluation.get("evidence_quotes") or [])
        if isinstance(item, dict)
    ]
    patterns = [
        item
        for item in (evaluation.get("recurring_patterns") or [])
        if isinstance(item, dict)
    ]
    parts = [
        item
        for item in (evaluation.get("part_performance") or [])
        if isinstance(item, dict)
    ]

    transcript_responses: list[dict[str, Any]] = []
    if speaking_attempt_id:
        for row in speaking_repo.list_speaking_responses(
            attempt_id=UUID(speaking_attempt_id)
        ):
            if str(row.get("status") or "") != "confirmed":
                continue
            transcript_responses.append(
                {
                    "id": str(row["id"]),
                    "question_id": str(row.get("question_id") or ""),
                    "part": int(row.get("part") or 1),
                    "sequence": int(row.get("sequence_number") or 1),
                    "prompt": "",
                    "duration_sec": max(0, int(row.get("duration_sec") or 0)),
                    "transcription_status": str(
                        row.get("transcription_status") or "not_queued"
                    ),
                    "transcript": str(row.get("transcript") or ""),
                }
            )
        speaking_attempt = speaking_repo.get_attempt(UUID(speaking_attempt_id))
        manifest = (
            speaking_attempt.get("speaking_manifest")
            if speaking_attempt
            and isinstance(speaking_attempt.get("speaking_manifest"), list)
            else []
        )
        by_qid = {
            str(item.get("id")): item
            for item in manifest
            if isinstance(item, dict) and item.get("id")
        }
        for item in transcript_responses:
            q = by_qid.get(item["question_id"])
            if q:
                item["prompt"] = str(q.get("prompt") or "")

    fluency = (
        score.get("attempt_metrics")
        if isinstance(score.get("attempt_metrics"), dict)
        else {}
    )

    return {
        "attempt_id": attempt_id,
        "hub_id": hub_id,
        "speaking_attempt_id": speaking_attempt_id or None,
        "status": str(attempt.get("status") or "completed"),
        "module": "speaking",
        "test_title": score.get("hub_title") or "Speaking practice",
        "ai_available": ai_evaluation_available(),
        "ai_status": ai_status,
        "ai_band": ai_band_f,
        "band_source": "ai" if ai_band_f is not None else "none",
        "ai_criteria": {
            k: float(v) for k, v in criteria.items() if isinstance(v, (int, float))
        },
        "ai_strengths": strengths,
        "ai_improvements": improvements,
        "next_band_advice": next_advice,
        "ai_parts": parts,
        "ai_evidence": evidence,
        "ai_patterns": patterns,
        "ai_fluency": fluency,
        "responses": transcript_responses,
        "ai_provider": score.get("provider_eval"),
        "ai_model_name": score.get("model_eval"),
        "submitted_at": attempt.get("completed_at"),
        "error": score.get("error"),
        "evaluation_status": (
            str(review.get("evaluation_status"))
            if review and review.get("evaluation_status")
            else None
        ),
    }
