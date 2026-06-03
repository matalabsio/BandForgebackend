"""Benchmark Reading start (orchestrated M01 path).

Usage:
  cd backend && source .venv/bin/activate
  python -m scripts.benchmark_reading_start
  python -m scripts.benchmark_reading_start --part 2 --cold
  python -m scripts.benchmark_reading_start --mock-attempt-id <uuid> --user-id <uuid>

## Reading Start flow map (POST /api/reading/{mock_test_id}/start)

Auth: JWT user lookup (router dependency).

When mock_attempt_id is set (full mock):

  Reads (Supabase / cache):
    1. mock_tests — get_mock_test
    2. test_attempts — abandon_stale (2 SELECTs + optional UPDATEs)
    3. unlock — read_unlock_snapshot (Redis) OR assert_module_unlocked DB path
    4. test_attempts — find_in_progress_reading_attempt
    5. test_attempts — earliest_reading_started_at (resume, shared clock)
    6. mock_test_modules — module_duration_minutes (via _reading_duration_seconds)
    7. questions — list_questions_public (passage + items)
    8. questions — count_questions_by_part (display_offset_before_part)

  Writes:
    - test_attempts UPDATE (stale abandon, optional)
    - test_attempts INSERT (new attempt)

  Redis:
    - reading_questions:{mock_test_id}:{part} — checked on start now; often cold
    - mock_progress unlock cache — read during assert_module_unlocked

  Object storage: none on start.

Likely duplication vs Listening fixes:
    - duplicate get_mock_test (removed in start path via test_row pass-through)
    - sync stale cleanup on hot path (~500–650ms class)
    - start path did not use reading_questions cache (now checked)
    - unlock may still hit DB if cache cold

Tables touched: users (auth), mock_tests, mock_attempts, test_attempts,
  questions, mock_test_modules; mock_progress cache keys.
"""

from __future__ import annotations

import argparse
import json
from uuid import UUID

from app.cache.hybrid_cache import delete_many
from app.cache.mock_cache import progress_cache_key, read_unlock_snapshot
from app.db.supabase_client import get_supabase
from app.mock_catalog.constants import M01_MOCK_TEST_ID
from app.reading import service
from app.reading.timing import ReadingStartTiming
from app.services import mock_orchestrator

M01 = UUID(M01_MOCK_TEST_ID)


def _find_mock(*, prefer_reading_open: bool = True) -> tuple[UUID, UUID, int] | None:
    from app.services import mock_orchestrator_repository as mor

    sb = get_supabase()
    rows = (
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
    candidates: list[tuple[UUID, UUID, int, int]] = []
    for row in rows:
        ma = UUID(str(row["id"]))
        uid = UUID(str(row["user_id"]))
        if not prefer_reading_open:
            return ma, uid, 1
        bundle = mor.fetch_mock_attempt_progress_bundle(
            mock_attempt_id=ma, user_id=uid
        )
        if not bundle:
            continue
        live = mor.live_question_parts(mock_test_id=M01, module="reading")
        done = {
            int(a["part"])
            for a in bundle.get("module_attempts") or []
            if a.get("module") == "reading"
            and a.get("status") == "completed"
            and a.get("part") is not None
        }
        next_part = next((p for p in sorted(live) if p not in done), None)
        if next_part is None:
            continue
        cur = str((bundle.get("mock_attempt") or {}).get("current_module") or "")
        score = 2 if cur == "reading" else 1
        candidates.append((ma, uid, next_part, score))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[3], reverse=True)
    ma, uid, part, _ = candidates[0]
    return ma, uid, part


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", type=int, default=1)
    parser.add_argument("--cold", action="store_true", help="Bust reading + unlock caches.")
    parser.add_argument("--mock-attempt-id", type=UUID, default=None)
    parser.add_argument("--user-id", type=UUID, default=None)
    parser.add_argument(
        "--warm-unlock",
        action="store_true",
        help="Warm unlock cache via finalize before start.",
    )
    args = parser.parse_args()

    if args.mock_attempt_id and args.user_id:
        mock_attempt_id, user_id = args.mock_attempt_id, args.user_id
        part = args.part
    else:
        found = _find_mock()
        if not found:
            print(
                json.dumps(
                    {
                        "error": "no in_progress M01 mock with open reading parts",
                        "hint": "Start a mock in the app or pass --mock-attempt-id.",
                    },
                    indent=2,
                )
            )
            return
        mock_attempt_id, user_id, part = found
        if args.part != 1:
            part = args.part

    if args.cold:
        delete_many(
            [
                f"reading_questions:{M01}:{part}",
                progress_cache_key(
                    mock_attempt_id=mock_attempt_id, user_id=user_id
                ),
                f"mock_session:{user_id}:{M01}",
            ]
        )
    if args.warm_unlock:
        mock_orchestrator._finalize_mock_progress_after_submit(
            mock_attempt_id=mock_attempt_id,
            mock_test_id=M01,
            user_id=user_id,
        )

    timing = ReadingStartTiming()
    service.start_attempt(
        mock_test_id=M01,
        user_id=user_id,
        part=part,
        mock_attempt_id=mock_attempt_id,
        include_questions=True,
        timing=timing,
    )
    out = {
        "scenario": "cold" if args.cold else "warm",
        "part": part,
        "mock_attempt_id": str(mock_attempt_id),
        **timing.to_log_fields(),
    }
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
