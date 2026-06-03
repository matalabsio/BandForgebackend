"""Lightweight concurrent load test for exam start/submit paths.

Usage:
  cd backend && source .venv/bin/activate
  python -m scripts.load_test_start_submit --workers 20 --rounds 2

Hits service layer directly (no HTTP) to stress Supabase + Redis orchestration.
"""

from __future__ import annotations

import argparse
import json
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter
from uuid import UUID

from app.listening import service as listening_service
from app.listening.timing import ListeningStartTiming, ListeningSubmitTiming
from app.mock_catalog.constants import M01_MOCK_TEST_ID
from app.services import mock_orchestrator

M01 = UUID(M01_MOCK_TEST_ID)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((pct / 100) * (len(ordered) - 1)))))
    return ordered[idx]


def _listening_round(*, user_id: UUID, mock_attempt_id: UUID) -> dict:
    out: dict = {"module": "listening", "errors": []}
    try:
        mock_orchestrator._finalize_mock_progress_after_submit(
            mock_attempt_id=mock_attempt_id,
            mock_test_id=M01,
            user_id=user_id,
        )
        timing = ListeningStartTiming()
        started = listening_service.start_attempt(
            mock_test_id=M01,
            user_id=user_id,
            part=1,
            mock_attempt_id=mock_attempt_id,
            include_questions=False,
            timing=timing,
        )
        out["start_ms"] = timing.duration_ms
        submit_timing = ListeningSubmitTiming()
        listening_service.submit_attempt(
            attempt_id=started.attempt_id,
            user_id=user_id,
            answers=[],
            timing=submit_timing,
        )
        out["submit_ms"] = submit_timing.duration_ms
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(str(exc))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--rounds", type=int, default=1)
    args = parser.parse_args()

    from app.db.supabase_client import get_supabase
    from app.services import mock_orchestrator_repository as mor

    sb = get_supabase()
    user_id = UUID(sb.table("users").select("id").limit(1).execute().data[0]["id"])

    def _spawn_mock() -> UUID:
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
        ma = mor.insert_mock_attempt(
            user_id=user_id, mock_test_id=M01, current_module="listening"
        )
        return UUID(str(ma["id"]))

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = []
        for _ in range(args.workers * args.rounds):
            ma = _spawn_mock()
            futures.append(
                pool.submit(_listening_round, user_id=user_id, mock_attempt_id=ma)
            )
        for fut in as_completed(futures):
            results.append(fut.result())

    starts = [r["start_ms"] for r in results if "start_ms" in r]
    submits = [r["submit_ms"] for r in results if "submit_ms" in r]
    errors = [e for r in results for e in r.get("errors", [])]

    summary = {
        "workers": args.workers,
        "rounds": args.rounds,
        "total_jobs": len(results),
        "error_count": len(errors),
        "error_rate_pct": round(100 * len(errors) / max(1, len(results)), 2),
        "start_ms": {
            "p50": round(_percentile(starts, 50)),
            "p95": round(_percentile(starts, 95)),
            "p99": round(_percentile(starts, 99)),
        },
        "submit_ms": {
            "p50": round(_percentile(submits, 50)),
            "p95": round(_percentile(submits, 95)),
            "p99": round(_percentile(submits, 99)),
        },
    }
    if errors[:3]:
        summary["sample_errors"] = errors[:3]
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
