"""Phase 2b: single-RPC persist for module submit (answers + complete + score)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.db.supabase_client import execute_with_retry, get_supabase

logger = logging.getLogger(__name__)


def _exec(query):
    return execute_with_retry(query.execute)


def _answers_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        qid = row.get("question_id")
        if qid is None:
            continue
        item: dict[str, Any] = {
            "question_id": str(qid),
            "user_answer": str(row.get("user_answer", "")),
        }
        if "is_correct" in row and row.get("is_correct") is not None:
            item["is_correct"] = bool(row["is_correct"])
        out.append(item)
    return out


def _score_payload(
    *,
    module: str,
    raw_score: int | None = None,
    correct_count: int | None = None,
    total_count: int | None = None,
    band: float,
    skill_breakdown: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "raw_score": raw_score,
        "correct_count": correct_count if correct_count is not None else raw_score,
        "total_count": total_count,
        "band": band,
        "skill_breakdown": skill_breakdown or {},
    }


def persist_module_submit_bundle(
    *,
    attempt_id: UUID,
    user_id: UUID,
    module: str,
    completed_at: datetime,
    answer_rows: list[dict[str, Any]],
    raw_score: int | None,
    total_count: int | None,
    band: float,
    skill_breakdown: dict[str, Any] | None = None,
    correct_count: int | None = None,
) -> dict[str, Any]:
    """
    Upsert answers, mark attempt completed, upsert module_scores in one DB round-trip.
    Falls back to sequential PostgREST calls if RPC is missing.
    """
    answers_json = _answers_payload(answer_rows)
    score_json = _score_payload(
        module=module,
        raw_score=raw_score,
        correct_count=correct_count,
        total_count=total_count,
        band=band,
        skill_breakdown=skill_breakdown,
    )
    completed_iso = completed_at.isoformat()

    client = get_supabase()
    try:
        result = _exec(
            client.rpc(
                "persist_module_submit_bundle",
                {
                    "p_attempt_id": str(attempt_id),
                    "p_user_id": str(user_id),
                    "p_completed_at": completed_iso,
                    "p_answers": answers_json,
                    "p_module": module,
                    "p_score": score_json,
                },
            )
        )
        data = result.data
        if isinstance(data, str):
            data = json.loads(data)
        if isinstance(data, dict):
            return data
    except Exception as exc:
        msg = str(exc).lower()
        if "attempt_not_found" in msg:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Test attempt not found.") from exc
        if "attempt_not_in_progress" in msg:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Attempt cannot be submitted (not in progress).",
            ) from exc
        if "module_mismatch" in msg:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Attempt module does not match submit payload.",
            ) from exc
        logger.warning(
            "persist_module_submit_bundle RPC unavailable, using sequential fallback: %s",
            exc,
        )

    return _persist_module_submit_sequential(
        attempt_id=attempt_id,
        user_id=user_id,
        module=module,
        completed_at_iso=completed_iso,
        answer_rows=answer_rows,
        raw_score=raw_score,
        total_count=total_count,
        band=band,
        skill_breakdown=skill_breakdown,
        correct_count=correct_count,
    )


def _persist_module_submit_sequential(
    *,
    attempt_id: UUID,
    user_id: UUID,
    module: str,
    completed_at_iso: str,
    answer_rows: list[dict[str, Any]],
    raw_score: int | None,
    total_count: int | None,
    band: float,
    skill_breakdown: dict[str, Any] | None,
    correct_count: int | None,
) -> dict[str, Any]:
    if module == "listening":
        from app.listening import repository as repo
    elif module == "reading":
        from app.reading import repository as repo
    elif module == "writing":
        from app.writing import repository as repo
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported module: {module}",
        )

    attempt = repo.get_attempt(attempt_id)
    if str(attempt.get("user_id")) != str(user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied.")
    if attempt.get("status") != "in_progress":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Attempt cannot be submitted (status={attempt.get('status')}).",
        )

    if module in ("listening", "reading"):
        repo.upsert_scored_answers(attempt_id=attempt_id, rows=answer_rows)
    else:
        for row in answer_rows:
            repo.upsert_answer(
                attempt_id=attempt_id,
                question_id=UUID(str(row["question_id"])),
                user_answer=str(row.get("user_answer", "")),
            )

    completed = repo.mark_attempt_completed(attempt_id, completed_at_iso=completed_at_iso)

    if module == "writing":
        wc = raw_score or 0
        part = int(attempt.get("part") or 1)
        repo.upsert_module_score(
            attempt_id=attempt_id,
            band=band,
            word_count=wc,
            part=part,
        )
    else:
        rs = raw_score or 0
        tot = total_count or 0
        repo.upsert_module_score(
            attempt_id=attempt_id,
            raw_score=rs,
            total=tot,
            band=band,
            skill_breakdown=skill_breakdown or {},
        )

    return completed
