"""Backfill hub materialization metadata for existing FSP study plans.

Usage:
    cd backend && source .venv/bin/activate
    python -m scripts.materialize_existing_plans
    python -m scripts.materialize_existing_plans --user-id <uuid>
    python -m scripts.materialize_existing_plans --dry-run
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from uuid import UUID

from app.db.supabase_client import execute_with_retry, get_supabase
from app.learning.service import (
    FULL_SKILL_PROGRAM_TIER,
    _materialize_study_plan_hubs,
    fetch_profile_row,
    invalidate_learning_profile_cache,
    warm_learning_profile_cache,
)


def _needs_materialization(study_plan: dict) -> bool:
    if not isinstance(study_plan, dict):
        return False
    weeks = study_plan.get("weeks")
    if not isinstance(weeks, list) or not weeks:
        return False
    return not study_plan.get("hubs_materialized_at")


def _iter_fsp_profiles(*, user_id: str | None) -> list[dict]:
    client = get_supabase()
    if user_id:
        row = fetch_profile_row(UUID(user_id))
        return [row] if row else []

    rows = execute_with_retry(
        lambda: (
            client.table("user_learning_profiles")
            .select("user_id, study_plan, plan_tier, prep_start, skill_weaknesses")
            .eq("plan_tier", FULL_SKILL_PROGRAM_TIER)
            .execute()
        )
    ).data or []
    return [r for r in rows if isinstance(r, dict)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    profiles = _iter_fsp_profiles(user_id=args.user_id)
    pending = [
        row
        for row in profiles
        if _needs_materialization(row.get("study_plan") or {})
    ]

    print(f"Found {len(pending)} profile(s) needing hub materialization")
    if args.dry_run:
        for row in pending:
            print(f"  would materialize: {row.get('user_id')}")
        return 0

    client = get_supabase()
    for row in pending:
        uid = UUID(str(row["user_id"]))
        study_plan = row.get("study_plan") or {}
        if not isinstance(study_plan, dict):
            continue
        print(f"Materializing plan for {uid} …")
        materialized = _materialize_study_plan_hubs(
            uid,
            dict(study_plan),
            skill_weaknesses=list(row.get("skill_weaknesses") or []),
            prep_start=None,
        )
        now = datetime.now(UTC).isoformat()
        execute_with_retry(
            lambda uid=uid, materialized=materialized, now=now: (
                client.table("user_learning_profiles")
                .update({"study_plan": materialized, "updated_at": now})
                .eq("user_id", str(uid))
                .execute()
            )
        )
        invalidate_learning_profile_cache(uid)
        warm_learning_profile_cache(uid)
        print(f"  done: {uid}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
