"""Load raw eval signals for a user's learning profile."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.db.supabase_client import execute_with_retry, get_supabase


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_user_target_band(user_id: UUID) -> float | None:
    client = get_supabase()
    rows = execute_with_retry(
        lambda: (
            client.table("users")
            .select("target_band")
            .eq("id", str(user_id))
            .limit(1)
            .execute()
        )
    ).data
    if not rows:
        return None
    return _safe_float(rows[0].get("target_band"))


def load_user_exam_and_target(user_id: UUID) -> dict[str, Any] | None:
    client = get_supabase()
    rows = execute_with_retry(
        lambda: (
            client.table("users")
            .select("target_band, exam_date, full_name, exam_module")
            .eq("id", str(user_id))
            .limit(1)
            .execute()
        )
    ).data
    return rows[0] if rows else None


def diagnostic_bands_from_attempt(attempt: dict[str, Any]) -> dict[str, float | None]:
    return {
        "listening": _safe_float(attempt.get("listening_band")),
        "reading": _safe_float(attempt.get("reading_band")),
        "writing": _safe_float(attempt.get("writing_band")),
        "speaking": _safe_float(attempt.get("speaking_band")),
    }


def load_lr_scores(user_id: UUID, *, limit: int = 40) -> list[dict[str, Any]]:
    """Listening/reading module_scores joined via test_attempts."""
    client = get_supabase()
    attempts = execute_with_retry(
        lambda: (
            client.table("test_attempts")
            .select("id, module, completed_at, status")
            .eq("user_id", str(user_id))
            .in_("module", ["listening", "reading"])
            .eq("status", "completed")
            .order("completed_at", desc=True)
            .limit(limit)
            .execute()
        )
    ).data or []
    if not attempts:
        return []

    attempt_ids = [str(a["id"]) for a in attempts]
    module_by_id = {str(a["id"]): a for a in attempts}

    scores = execute_with_retry(
        lambda: (
            client.table("module_scores")
            .select("attempt_id, band, skill_breakdown, correct_count, total_count")
            .in_("attempt_id", attempt_ids)
            .execute()
        )
    ).data or []

    out: list[dict[str, Any]] = []
    for row in scores:
        aid = str(row.get("attempt_id") or "")
        attempt = module_by_id.get(aid)
        if not attempt:
            continue
        out.append(
            {
                "attempt_id": aid,
                "module": attempt.get("module"),
                "completed_at": attempt.get("completed_at"),
                "band": _safe_float(row.get("band")),
                "skill_breakdown": row.get("skill_breakdown") or {},
                "correct_count": row.get("correct_count"),
                "total_count": row.get("total_count"),
            }
        )
    # Preserve attempt order (newest first)
    order = {aid: i for i, aid in enumerate(attempt_ids)}
    out.sort(key=lambda r: order.get(str(r["attempt_id"]), 999))
    return out


def load_writing_reviews(user_id: UUID, *, limit: int = 20) -> list[dict[str, Any]]:
    client = get_supabase()
    attempts = execute_with_retry(
        lambda: (
            client.table("test_attempts")
            .select("id, completed_at")
            .eq("user_id", str(user_id))
            .eq("module", "writing")
            .order("started_at", desc=True)
            .limit(limit)
            .execute()
        )
    ).data or []
    if not attempts:
        return []

    attempt_ids = [str(a["id"]) for a in attempts]
    completed_at_by_id = {str(a["id"]): a.get("completed_at") for a in attempts}

    reviews = execute_with_retry(
        lambda: (
            client.table("writing_reviews")
            .select(
                "id, attempt_id, status, human_band, human_criteria_scores, ai_scores, reviewed_at"
            )
            .in_("attempt_id", attempt_ids)
            .execute()
        )
    ).data or []

    out: list[dict[str, Any]] = []
    for row in reviews:
        aid = str(row.get("attempt_id") or "")
        ai = row.get("ai_scores") if isinstance(row.get("ai_scores"), dict) else {}
        human_band = _safe_float(row.get("human_band"))
        ai_band = _safe_float(ai.get("ai_band"))
        status = str(row.get("status") or "")
        band = human_band if status == "completed" and human_band is not None else ai_band
        criteria = (
            row.get("human_criteria_scores")
            if status == "completed" and isinstance(row.get("human_criteria_scores"), dict)
            else (ai.get("criteria") if isinstance(ai.get("criteria"), dict) else {})
        )
        out.append(
            {
                "attempt_id": aid,
                "module": "writing",
                "completed_at": completed_at_by_id.get(aid) or row.get("reviewed_at"),
                "band": band,
                "criteria": criteria or {},
                "improvements": list(ai.get("improvements") or []),
                "grammar_mistakes": list(ai.get("grammar_mistakes") or []),
                "vocabulary_highlights": list(ai.get("vocabulary_highlights") or []),
                "status": status,
            }
        )
    return out


def load_speaking_reviews(user_id: UUID, *, limit: int = 20) -> list[dict[str, Any]]:
    client = get_supabase()
    attempts = execute_with_retry(
        lambda: (
            client.table("test_attempts")
            .select("id, completed_at")
            .eq("user_id", str(user_id))
            .eq("module", "speaking")
            .order("started_at", desc=True)
            .limit(limit)
            .execute()
        )
    ).data or []
    if not attempts:
        return []

    attempt_ids = [str(a["id"]) for a in attempts]
    completed_at_by_id = {str(a["id"]): a.get("completed_at") for a in attempts}

    reviews = execute_with_retry(
        lambda: (
            client.table("speaking_reviews")
            .select(
                "id, attempt_id, status, human_band, human_criteria_scores, ai_scores, reviewed_at"
            )
            .in_("attempt_id", attempt_ids)
            .execute()
        )
    ).data or []

    out: list[dict[str, Any]] = []
    for row in reviews:
        aid = str(row.get("attempt_id") or "")
        ai = row.get("ai_scores") if isinstance(row.get("ai_scores"), dict) else {}
        evaluation = ai.get("evaluation") if isinstance(ai.get("evaluation"), dict) else {}
        human_band = _safe_float(row.get("human_band"))
        ai_band = _safe_float(ai.get("ai_band"))
        status = str(row.get("status") or "")
        band = human_band if status == "completed" and human_band is not None else ai_band

        human_criteria = row.get("human_criteria_scores")
        if status == "completed" and isinstance(human_criteria, dict) and human_criteria:
            criteria = human_criteria
        else:
            band_scores = evaluation.get("band_scores") if isinstance(evaluation, dict) else None
            if isinstance(band_scores, dict) and band_scores:
                criteria = {
                    "fluency": _safe_float(band_scores.get("FC")),
                    "lexical": _safe_float(band_scores.get("LR")),
                    "grammar": _safe_float(band_scores.get("GRA")),
                    "pronunciation": _safe_float(band_scores.get("P")),
                }
            else:
                criteria = {
                    "fluency": _safe_float(ai.get("fluency")),
                    "lexical": _safe_float(ai.get("lexical")),
                    "grammar": _safe_float(ai.get("grammar")),
                    "pronunciation": _safe_float(ai.get("pronunciation")),
                }

        vocab_raw = evaluation.get("vocabulary_highlights") or ai.get("vocabulary_highlights") or []
        vocab_highlights: list[Any] = []
        if isinstance(vocab_raw, list):
            for item in vocab_raw:
                if isinstance(item, str):
                    vocab_highlights.append({"word": item, "polarity": "weak", "alternatives": []})
                elif isinstance(item, dict):
                    vocab_highlights.append(item)

        improvements = list(evaluation.get("improvements") or ai.get("improvements") or [])
        recurring = list(evaluation.get("recurring_patterns") or [])

        out.append(
            {
                "attempt_id": aid,
                "module": "speaking",
                "completed_at": completed_at_by_id.get(aid) or row.get("reviewed_at"),
                "band": band,
                "criteria": {k: v for k, v in criteria.items() if v is not None},
                "improvements": improvements,
                "grammar_mistakes": [],
                "vocabulary_highlights": vocab_highlights,
                "recurring_patterns": recurring,
                "status": status,
            }
        )
    return out


def load_diagnostic_seed(user_id: UUID) -> dict[str, Any] | None:
    """Optional diagnostic attempt linked to this user."""
    client = get_supabase()
    rows = execute_with_retry(
        lambda: (
            client.table("diagnostic_attempts")
            .select(
                "id, client_attempt_id, listening_band, reading_band, writing_band, "
                "speaking_band, aggregate_band, completed_at"
            )
            .eq("user_id", str(user_id))
            .order("completed_at", desc=True)
            .limit(1)
            .execute()
        )
    ).data or []
    if not rows:
        return None

    attempt = rows[0]
    client_attempt_id = str(attempt.get("client_attempt_id") or "")
    evals: list[dict[str, Any]] = []
    if client_attempt_id:
        evals = execute_with_retry(
            lambda: (
                client.table("diagnostic_ai_evaluations")
                .select("overall_band, criteria_scores, feedback, evaluation_type")
                .eq("client_attempt_id", client_attempt_id)
                .execute()
            )
        ).data or []

    return {
        "attempt": attempt,
        "evaluations": evals or [],
    }


def load_all_sources(user_id: UUID) -> dict[str, Any]:
    """Parallel load of learning signals (Phase 4)."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=5) as pool:
        fut_target = pool.submit(load_user_target_band, user_id)
        fut_lr = pool.submit(load_lr_scores, user_id)
        fut_writing = pool.submit(load_writing_reviews, user_id)
        fut_speaking = pool.submit(load_speaking_reviews, user_id)
        fut_diag = pool.submit(load_diagnostic_seed, user_id)
        return {
            "target_band": fut_target.result(),
            "lr_scores": fut_lr.result(),
            "writing": fut_writing.result(),
            "speaking": fut_speaking.result(),
            "diagnostic": fut_diag.result(),
        }
