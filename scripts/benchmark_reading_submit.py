"""Benchmark Reading submit (orchestrated M01 path).

Usage:
  cd backend && source .venv/bin/activate
  python -m scripts.benchmark_reading_submit
  python -m scripts.benchmark_reading_submit --dry-run
  python -m scripts.benchmark_reading_submit --fresh-mock

Reuses bootstrap patterns from benchmark_listening_submit.py.
"""

from __future__ import annotations

import argparse
import json
from time import perf_counter
from uuid import UUID

from app.db.supabase_client import get_supabase
from app.mock_catalog.constants import M01_MOCK_TEST_ID
from app.reading import repository as repo
from app.reading import service
from app.reading.evaluation import score_answers
from app.reading.timing import ReadingSubmitTiming
from app.services import mock_orchestrator
from app.services import mock_orchestrator_repository as mor

M01 = UUID(M01_MOCK_TEST_ID)


def _ms(start: float) -> int:
    return round((perf_counter() - start) * 1000)


def profile_submit_dry(*, attempt_id: UUID, user_id: UUID) -> dict:
    out: dict = {"attempt_id": str(attempt_id), "dry_run": True}
    t0 = perf_counter()
    attempt = repo.get_attempt(attempt_id)
    service._ensure_owner(attempt, user_id)
    out["attempt_ms"] = _ms(t0)
    from app.reading.service import _content_part

    live_part = int(attempt["part"]) if attempt.get("part") is not None else 1
    content_part = _content_part(mock_test_id=M01, live_part=live_part)
    t0 = perf_counter()
    questions = repo.list_questions_for_scoring(M01, part=content_part)
    out["scoring_query_ms"] = _ms(t0)
    answers_by_qid = {str(q["id"]): "" for q in questions}
    t0 = perf_counter()
    score_answers(questions=questions, answers_by_qid=answers_by_qid)
    out["scoring_compute_ms"] = _ms(t0)
    out["note"] = "dry-run: RPC + progress not executed"
    return out


def profile_submit_live(*, attempt_id: UUID, user_id: UUID) -> dict:
    timing = ReadingSubmitTiming()
    row = repo.get_attempt(attempt_id)
    from app.reading.service import _content_part

    live_part = int(row.get("part") or 1)
    content_part = _content_part(mock_test_id=M01, live_part=live_part)
    questions = repo.list_questions_for_scoring(M01, part=content_part)
    answers = [{"question_id": str(q["id"]), "user_answer": ""} for q in questions]
    service.submit_attempt(
        attempt_id=attempt_id,
        user_id=user_id,
        answers=answers,
        timing=timing,
    )
    return {
        "attempt_id": str(attempt_id),
        "part": row.get("part"),
        "mock_attempt_id": row.get("mock_attempt_id"),
        "dry_run": False,
        **timing.to_log_fields(),
    }


def find_in_progress() -> list[dict]:
    sb = get_supabase()
    return (
        sb.table("test_attempts")
        .select("id,user_id,part,mock_attempt_id")
        .eq("module", "reading")
        .eq("status", "in_progress")
        .eq("mock_test_id", str(M01))
        .limit(5)
        .execute()
        .data
        or []
    )


def _next_reading_part(*, mock_attempt_id: UUID, user_id: UUID) -> int | None:
    bundle = mor.fetch_mock_attempt_progress_bundle(
        mock_attempt_id=mock_attempt_id, user_id=user_id
    )
    if not bundle:
        return None
    live = mor.live_question_parts(mock_test_id=M01, module="reading")
    done = {
        int(a["part"])
        for a in bundle.get("module_attempts") or []
        if a.get("module") == "reading"
        and a.get("status") == "completed"
        and a.get("part") is not None
    }
    for part in sorted(live):
        if part not in done:
            return part
    return None


def _bootstrap_start_part(
    *, mock_attempt_id: UUID, user_id: UUID, part: int, note: str
) -> dict:
    mock_orchestrator._finalize_mock_progress_after_submit(
        mock_attempt_id=mock_attempt_id,
        mock_test_id=M01,
        user_id=user_id,
    )
    started = service.start_attempt(
        mock_test_id=M01,
        user_id=user_id,
        part=part,
        mock_attempt_id=mock_attempt_id,
        include_questions=False,
    )
    return {
        "id": str(started.attempt_id),
        "user_id": str(user_id),
        "part": part,
        "mock_attempt_id": str(mock_attempt_id),
        "bootstrap_note": note,
    }


def _abandon_in_progress_m01(*, user_id: UUID) -> None:
    sb = get_supabase()
    for row in (
        sb.table("mock_attempts")
        .select("id")
        .eq("user_id", str(user_id))
        .eq("mock_test_id", str(M01))
        .eq("status", "in_progress")
        .execute()
        .data
        or []
    ):
        mor.update_mock_attempt(
            mock_attempt_id=UUID(str(row["id"])),
            fields={"status": "abandoned", "current_module": None},
        )


def bootstrap_orchestrated(*, fresh_mock: bool = False) -> dict:
    sb = get_supabase()
    mock_rows = (
        sb.table("mock_attempts")
        .select("id,user_id")
        .eq("mock_test_id", str(M01))
        .eq("status", "in_progress")
        .order("started_at", desc=True)
        .limit(10)
        .execute()
        .data
        or []
    )
    if fresh_mock:
        user_id = UUID(
            mock_rows[0]["user_id"]
            if mock_rows
            else sb.table("users").select("id").limit(1).execute().data[0]["id"]
        )
        _abandon_in_progress_m01(user_id=user_id)
        ma = mor.insert_mock_attempt(
            user_id=user_id, mock_test_id=M01, current_module="reading"
        )
        return _bootstrap_start_part(
            mock_attempt_id=UUID(str(ma["id"])),
            user_id=user_id,
            part=1,
            note="fresh mock + reading part 1",
        )

    errors: list[str] = []
    for row in mock_rows:
        mock_attempt_id = UUID(str(row["id"]))
        user_id = UUID(str(row["user_id"]))
        part = _next_reading_part(
            mock_attempt_id=mock_attempt_id, user_id=user_id
        )
        if part is None:
            errors.append(f"{mock_attempt_id}: reading complete")
            continue
        try:
            return _bootstrap_start_part(
                mock_attempt_id=mock_attempt_id,
                user_id=user_id,
                part=part,
                note=f"started reading part {part}",
            )
        except Exception as exc:
            errors.append(f"{mock_attempt_id} p{part}: {exc}")

    if mock_rows:
        user_id = UUID(str(mock_rows[0]["user_id"]))
        _abandon_in_progress_m01(user_id=user_id)
        ma = mor.insert_mock_attempt(
            user_id=user_id, mock_test_id=M01, current_module="reading"
        )
        return _bootstrap_start_part(
            mock_attempt_id=UUID(str(ma["id"])),
            user_id=user_id,
            part=1,
            note="fallback fresh mock",
        )
    raise RuntimeError("; ".join(errors) or "no mock_attempt")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt-id", type=UUID, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-bootstrap", action="store_true")
    parser.add_argument("--fresh-mock", action="store_true")
    args = parser.parse_args()

    meta: dict | None = None
    if args.attempt_id:
        attempt = repo.get_attempt(args.attempt_id)
        attempt_id = args.attempt_id
        user_id = UUID(str(attempt["user_id"]))
    else:
        rows = find_in_progress()
        if not rows:
            if args.no_bootstrap:
                print(json.dumps({"error": "no in_progress reading"}))
                return
            row = bootstrap_orchestrated(fresh_mock=args.fresh_mock)
            meta = {k: row[k] for k in ("bootstrap_note",) if k in row}
            attempt_id = UUID(str(row["id"]))
            user_id = UUID(str(row["user_id"]))
        else:
            row = rows[0]
            attempt_id = UUID(str(row["id"]))
            user_id = UUID(str(row["user_id"]))

    result = (
        profile_submit_dry(attempt_id=attempt_id, user_id=user_id)
        if args.dry_run
        else profile_submit_live(attempt_id=attempt_id, user_id=user_id)
    )
    if meta:
        result = {**meta, **result}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
