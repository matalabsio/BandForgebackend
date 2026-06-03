"""Benchmark Writing start (orchestrated M01 path).

Usage:
  cd backend && source .venv/bin/activate
  python -m scripts.benchmark_writing_start
  python -m scripts.benchmark_writing_start --part 1 --cold
  python -m scripts.benchmark_writing_start --mock-attempt-id <uuid> --user-id <uuid>

## Writing Start flow map (POST /api/writing/{mock_test_id}/start)

Auth: JWT user lookup (router dependency).

When mock_attempt_id is set (full mock):

  Reads (Supabase / cache):
    1. unlock — read_unlock_snapshot (Redis) OR assert_module_unlocked DB path
    2. test_attempts — find_in_progress_writing_attempt
    3. mock_tests — get_mock_test (inside _pack_task)
    4. questions — list_questions_for_part (task prompt + options)
    5. answers — get_answer_for_attempt (resume only)

  Writes:
    - test_attempts UPDATE (optional abandon on scope mismatch / force_new)
    - test_attempts INSERT (new attempt)

  Redis:
    - mock_progress unlock cache — read during assert_module_unlocked
    - no writing task cache today

  Object storage: none on start.

Likely optimization targets (same patterns as Listening/Reading):
    - duplicate get_mock_test on every start (no pass-through yet)
    - unlock DB rebuild when cache cold
    - no task/prompt cache on start
    - no async stale cleanup (writing has none today; orchestrator may abandon on module switch)

Tables touched: users (auth), mock_tests, mock_attempts, test_attempts, questions,
  answers (resume); mock_progress cache keys.
"""

from __future__ import annotations

import argparse
import json
from uuid import UUID

from app.cache.hybrid_cache import delete_many
from app.cache.mock_cache import progress_cache_key
from app.db.supabase_client import get_supabase
from app.mock_catalog.constants import M01_MOCK_TEST_ID
from app.writing import service
from app.writing.timing import WritingStartTiming
from app.services import mock_orchestrator

M01 = UUID(M01_MOCK_TEST_ID)


def _writing_unlocked_db(
    *, mock_attempt_id: UUID, user_id: UUID, part: int
) -> bool:
    from app.services import mock_orchestrator_repository as mor
    from app.services.mock_orchestrator import (
        _validate_unlock_from_snapshot,
        build_unlock_snapshot,
    )

    bundle = mor.fetch_mock_attempt_progress_bundle(
        mock_attempt_id=mock_attempt_id, user_id=user_id
    )
    if not bundle:
        return False
    mock_row = bundle.get("mock_attempt") or {}
    unlock = build_unlock_snapshot(
        mock_test_id=M01,
        modules=bundle.get("modules") or mor.list_mock_modules(M01),
        module_attempts=bundle.get("module_attempts") or [],
        current_module=mock_row.get("current_module"),
    )
    try:
        _validate_unlock_from_snapshot(
            snapshot=unlock,
            mock_test_id=M01,
            module="writing",
            part=part,
        )
        return True
    except Exception:
        return False


def _find_mock(*, prefer_writing_open: bool = True) -> tuple[UUID, UUID, int] | None:
    from app.services import mock_orchestrator_repository as mor

    sb = get_supabase()
    rows = (
        sb.table("mock_attempts")
        .select("id,user_id,status,current_module")
        .eq("mock_test_id", str(M01))
        .order("started_at", desc=True)
        .limit(30)
        .execute()
        .data
        or []
    )
    candidates: list[tuple[UUID, UUID, int, int]] = []
    for row in rows:
        ma = UUID(str(row["id"]))
        uid = UUID(str(row["user_id"]))
        if not prefer_writing_open:
            return ma, uid, 1
        bundle = mor.fetch_mock_attempt_progress_bundle(
            mock_attempt_id=ma, user_id=uid
        )
        if not bundle:
            continue
        live = mor.live_question_parts(mock_test_id=M01, module="writing")
        done = {
            int(a["part"])
            for a in bundle.get("module_attempts") or []
            if a.get("module") == "writing"
            and a.get("status") == "completed"
            and a.get("part") is not None
        }
        next_part = next((p for p in sorted(live) if p not in done), None)
        if next_part is None:
            continue
        if not _writing_unlocked_db(
            mock_attempt_id=ma, user_id=uid, part=next_part
        ):
            continue
        cur = str((bundle.get("mock_attempt") or {}).get("current_module") or "")
        score = 0
        if str(row.get("status")) == "in_progress":
            score += 2
        if cur == "writing":
            score += 2
        candidates.append((ma, uid, next_part, score))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[3], reverse=True)
    ma, uid, part, _ = candidates[0]
    return ma, uid, part


def _bootstrap_fresh_mock(*, part: int = 1) -> tuple[UUID, UUID, int]:
    """Reuse the best unlock-valid mock; start a new writing attempt on it."""
    found = _find_mock()
    if not found:
        raise RuntimeError(
            "no M01 mock with writing unlocked — complete listening/reading first"
        )
    mock_attempt_id, user_id, open_part = found
    target_part = part if part in (1, 2) else open_part
    mock_orchestrator._finalize_mock_progress_after_submit(
        mock_attempt_id=mock_attempt_id,
        mock_test_id=M01,
        user_id=user_id,
    )
    return mock_attempt_id, user_id, target_part


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", type=int, default=1)
    parser.add_argument("--cold", action="store_true", help="Bust unlock cache.")
    parser.add_argument("--mock-attempt-id", type=UUID, default=None)
    parser.add_argument("--user-id", type=UUID, default=None)
    parser.add_argument(
        "--warm-unlock",
        action="store_true",
        help="Warm unlock cache via finalize before start.",
    )
    parser.add_argument(
        "--fresh-mock",
        action="store_true",
        help="Reuse best unlock-valid mock and warm unlock cache.",
    )
    args = parser.parse_args()

    if args.mock_attempt_id and args.user_id:
        mock_attempt_id, user_id = args.mock_attempt_id, args.user_id
        part = args.part
    elif args.fresh_mock:
        mock_attempt_id, user_id, part = _bootstrap_fresh_mock(
            part=args.part if args.part != 1 else 1
        )
        if args.part != 1:
            part = args.part
    else:
        found = _find_mock()
        if not found:
            print(
                json.dumps(
                    {
                        "error": "no in_progress M01 mock with open writing parts",
                        "hint": "Advance a mock to writing or pass --mock-attempt-id.",
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

    timing = WritingStartTiming()
    service.start_attempt(
        mock_test_id=M01,
        user_id=user_id,
        part=part,
        mock_attempt_id=mock_attempt_id,
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
