"""Benchmark Writing autosave (orchestrated M01 path).

Usage:
  cd backend && source .venv/bin/activate
  python -m scripts.benchmark_writing_autosave
  python -m scripts.benchmark_writing_autosave --attempt-id <uuid>
  python -m scripts.benchmark_writing_autosave --fresh-mock

## Writing Autosave flow map (POST /api/writing/attempts/{attempt_id}/autosave)

  Reads:
    1. test_attempts — get_attempt (ownership + status)
    2. questions — question_belongs_to (validate question_id)

  Writes:
    1. answers — upsert_answer (on_conflict attempt_id,question_id)

  Redis: none
  Object storage: none

Likely optimization targets:
    - redundant question_belongs_to query (could cache task id on start)
    - execute_with_retry on autosave (3 retries, 0.2s base delay)
"""

from __future__ import annotations

import argparse
import json
from uuid import UUID

from app.db.supabase_client import get_supabase
from app.mock_catalog.constants import M01_MOCK_TEST_ID
from app.writing import repository as repo
from app.writing import service
from app.writing.timing import WritingAutosaveTiming

M01 = UUID(M01_MOCK_TEST_ID)


def find_in_progress() -> list[dict]:
    sb = get_supabase()
    return (
        sb.table("test_attempts")
        .select("id,user_id,part,mock_attempt_id")
        .eq("module", "writing")
        .eq("status", "in_progress")
        .eq("mock_test_id", str(M01))
        .limit(5)
        .execute()
        .data
        or []
    )


def _question_id_for_attempt(*, attempt_id: UUID, part: int) -> UUID:
    rows = repo.list_questions_for_part(mock_test_id=M01, part=part)
    if not rows:
        raise RuntimeError(f"no writing task for part {part}")
    return UUID(str(rows[0]["id"]))


def bootstrap_attempt(*, fresh_mock: bool = False) -> dict:
    from scripts.benchmark_writing_submit import bootstrap_orchestrated

    row = bootstrap_orchestrated(fresh_mock=fresh_mock)
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt-id", type=UUID, default=None)
    parser.add_argument("--no-bootstrap", action="store_true")
    parser.add_argument("--fresh-mock", action="store_true")
    args = parser.parse_args()

    meta: dict | None = None
    if args.attempt_id:
        attempt = repo.get_attempt(args.attempt_id)
        attempt_id = args.attempt_id
        user_id = UUID(str(attempt["user_id"]))
        part = int(attempt.get("part") or 1)
    else:
        rows = find_in_progress()
        if not rows:
            if args.no_bootstrap:
                print(json.dumps({"error": "no in_progress writing"}))
                return
            row = bootstrap_attempt(fresh_mock=args.fresh_mock)
            meta = {k: row[k] for k in ("bootstrap_note",) if k in row}
            attempt_id = UUID(str(row["id"]))
            user_id = UUID(str(row["user_id"]))
            part = int(row.get("part") or 1)
        else:
            row = rows[0]
            attempt_id = UUID(str(row["id"]))
            user_id = UUID(str(row["user_id"]))
            part = int(row.get("part") or 1)

    question_id = _question_id_for_attempt(attempt_id=attempt_id, part=part)
    timing = WritingAutosaveTiming()
    service.autosave_answer(
        attempt_id=attempt_id,
        user_id=user_id,
        question_id=question_id,
        user_answer="Benchmark autosave sample text for latency measurement.",
        timing=timing,
    )
    out = {
        "attempt_id": str(attempt_id),
        "part": part,
        "question_id": str(question_id),
        **timing.to_log_fields(),
    }
    if meta:
        out = {**meta, **out}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
