"""Profile Listening submit phases (dev Supabase).

Usage:
  cd backend && source .venv/bin/activate
  python -m scripts.benchmark_listening_submit
  python -m scripts.benchmark_listening_submit --dry-run
  python -m scripts.benchmark_listening_submit --attempt-id <uuid>
  python -m scripts.benchmark_listening_submit --no-bootstrap

By default, if no in_progress listening row exists, the script starts the next
unlocked part on an in_progress M01 mock_attempt (orchestrated path), then submits.
"""

from __future__ import annotations

import argparse
import json
from time import perf_counter
from uuid import UUID

from app.db.supabase_client import get_supabase
from app.listening import repository as repo
from app.listening import service
from app.listening.evaluation import score_answers
from app.listening.timing import ListeningSubmitTiming
from app.mock_catalog.constants import M01_MOCK_TEST_ID
from app.services import mock_orchestrator
from app.services import mock_orchestrator_repository as mor

M01 = UUID(M01_MOCK_TEST_ID)


def _ms(start: float) -> int:
    return round((perf_counter() - start) * 1000)


def profile_submit_dry(*, attempt_id: UUID, user_id: UUID) -> dict:
    """Read + score only; no DB writes."""
    out: dict = {"attempt_id": str(attempt_id), "dry_run": True}
    t0 = perf_counter()
    attempt = repo.get_attempt(attempt_id)
    service._ensure_owner(attempt, user_id)
    out["attempt_ms"] = _ms(t0)

    part = int(attempt["part"]) if attempt.get("part") is not None else None
    t0 = perf_counter()
    questions = repo.list_questions_for_scoring(M01, part=part)
    out["scoring_query_ms"] = _ms(t0)

    answers_by_qid = {str(q["id"]): "" for q in questions}
    t0 = perf_counter()
    score_answers(questions=questions, answers_by_qid=answers_by_qid)
    out["scoring_compute_ms"] = _ms(t0)
    out["rpc_bundle_ms"] = 0
    out["progress_ms"] = 0
    out["note"] = "dry-run: RPC + progress not executed"
    return out


def profile_submit_live(*, attempt_id: UUID, user_id: UUID) -> dict:
    timing = ListeningSubmitTiming()
    row = repo.get_attempt(attempt_id)
    questions = repo.list_questions_for_scoring(
        M01, part=int(row.get("part") or 1)
    )
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
        .select("id,user_id,mock_test_id,part,status,mock_attempt_id")
        .eq("module", "listening")
        .eq("status", "in_progress")
        .eq("mock_test_id", str(M01))
        .limit(5)
        .execute()
        .data
        or []
    )


def _next_listening_part(*, mock_attempt_id: UUID, user_id: UUID) -> int | None:
    """First listening part not yet completed for this mock session."""
    bundle = mor.fetch_mock_attempt_progress_bundle(
        mock_attempt_id=mock_attempt_id, user_id=user_id
    )
    if not bundle:
        return None
    live = mor.live_question_parts(mock_test_id=M01, module="listening")
    done = {
        int(a["part"])
        for a in bundle.get("module_attempts") or []
        if a.get("module") == "listening"
        and a.get("status") == "completed"
        and a.get("part") is not None
    }
    for part in sorted(live):
        if part not in done:
            return part
    return None


def _bootstrap_start_part(
    *,
    mock_attempt_id: UUID,
    user_id: UUID,
    part: int,
    note_prefix: str,
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
        "bootstrapped": True,
        "bootstrap_note": (
            f"{note_prefix} listening part {part} on mock_attempt {mock_attempt_id} "
            "(no questions loaded)."
        ),
    }


def _abandon_in_progress_m01_for_user(*, user_id: UUID) -> list[str]:
    """One in_progress mock per (user, mock_test) — must abandon before inserting another."""
    sb = get_supabase()
    rows = (
        sb.table("mock_attempts")
        .select("id")
        .eq("user_id", str(user_id))
        .eq("mock_test_id", str(M01))
        .eq("status", "in_progress")
        .execute()
        .data
        or []
    )
    abandoned: list[str] = []
    for row in rows:
        mid = UUID(str(row["id"]))
        mor.update_mock_attempt(
            mock_attempt_id=mid,
            fields={"status": "abandoned", "current_module": None},
        )
        abandoned.append(str(mid))
    return abandoned


def bootstrap_fresh_mock_attempt(*, user_id: UUID) -> dict:
    """New M01 mock_attempt when existing sessions have finished all listening parts."""
    abandoned = _abandon_in_progress_m01_for_user(user_id=user_id)
    ma_row = mor.insert_mock_attempt(
        user_id=user_id,
        mock_test_id=M01,
        current_module="listening",
    )
    mock_attempt_id = UUID(str(ma_row["id"]))
    note = "Created fresh mock_attempt and started"
    if abandoned:
        note += f" (abandoned {len(abandoned)} prior in_progress mock(s))"
    return _bootstrap_start_part(
        mock_attempt_id=mock_attempt_id,
        user_id=user_id,
        part=1,
        note_prefix=note,
    )


def bootstrap_orchestrated_attempt(*, fresh_mock: bool = False) -> dict:
    """
    Start listening for the next unlocked part on an in_progress M01 mock_attempt.
    Returns a test_attempts-shaped dict (id, user_id, ...).
    """
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
        if not mock_rows:
            user_row = sb.table("users").select("id").limit(1).execute().data
            if not user_row:
                raise RuntimeError("No users in database for fresh mock bootstrap.")
            user_id = UUID(str(user_row[0]["id"]))
        else:
            user_id = UUID(str(mock_rows[0]["user_id"]))
        return bootstrap_fresh_mock_attempt(user_id=user_id)

    if not mock_rows:
        raise RuntimeError(
            "No in_progress mock_attempt for M01. Start a full mock in the app first, "
            "or pass --fresh-mock to create a new session for benchmarking."
        )

    errors: list[str] = []
    for row in mock_rows:
        mock_attempt_id = UUID(str(row["id"]))
        user_id = UUID(str(row["user_id"]))
        part = _next_listening_part(
            mock_attempt_id=mock_attempt_id, user_id=user_id
        )
        if part is None:
            errors.append(f"mock {mock_attempt_id}: all listening parts completed")
            continue
        try:
            return _bootstrap_start_part(
                mock_attempt_id=mock_attempt_id,
                user_id=user_id,
                part=part,
                note_prefix="Started",
            )
        except Exception as exc:
            errors.append(f"mock {mock_attempt_id} part {part}: {exc}")
            continue

    # Dev fallback: prior benchmark runs often exhaust listening on all open mocks.
    user_id = UUID(str(mock_rows[0]["user_id"]))
    try:
        result = bootstrap_fresh_mock_attempt(user_id=user_id)
        result["bootstrap_fallback"] = (
            "All in_progress mocks had listening complete; created a new mock_attempt."
        )
        if errors:
            result["bootstrap_skipped"] = errors
        return result
    except Exception as exc:
        errors.append(f"fresh mock: {exc}")

    raise RuntimeError(
        "; ".join(errors)
        or "Could not bootstrap a listening attempt on any in_progress M01 mock."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt-id", type=UUID, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Profile read/score only (no submit side effects).",
    )
    parser.add_argument(
        "--no-bootstrap",
        action="store_true",
        help="Do not auto-start a part when no in_progress listening row exists.",
    )
    parser.add_argument(
        "--fresh-mock",
        action="store_true",
        help="Always create a new in_progress mock_attempt and start listening part 1.",
    )
    args = parser.parse_args()

    bootstrap_meta: dict | None = None

    if args.attempt_id:
        attempt = repo.get_attempt(args.attempt_id)
        user_id = UUID(str(attempt["user_id"]))
        attempt_id = args.attempt_id
        row = {"id": str(attempt_id), "part": attempt.get("part")}
    else:
        candidates = find_in_progress()
        if not candidates:
            if args.no_bootstrap:
                print(
                    json.dumps(
                        {
                            "error": "no in_progress listening attempts for M01",
                            "hint": (
                                "Run without --no-bootstrap to auto-start the next "
                                "unlocked part, or start listening in the app first."
                            ),
                        },
                        indent=2,
                    )
                )
                return
            try:
                row = bootstrap_orchestrated_attempt(fresh_mock=args.fresh_mock)
                bootstrap_meta = {
                    k: row[k]
                    for k in (
                        "bootstrapped",
                        "bootstrap_note",
                        "bootstrap_fallback",
                        "bootstrap_skipped",
                    )
                    if row.get(k) is not None
                }
            except RuntimeError as exc:
                print(json.dumps({"error": str(exc)}, indent=2))
                return
        else:
            row = candidates[0]
        attempt_id = UUID(str(row["id"]))
        user_id = UUID(str(row["user_id"]))

    if args.dry_run:
        result = profile_submit_dry(attempt_id=attempt_id, user_id=user_id)
    else:
        result = profile_submit_live(attempt_id=attempt_id, user_id=user_id)

    if bootstrap_meta:
        result = {**bootstrap_meta, **result}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
