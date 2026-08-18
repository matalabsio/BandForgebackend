#!/usr/bin/env python3
"""Staging diagnostic for Question Bank assignment invariants.

Reports duplicate set/hub ids, ledger/plan mismatches, non-bank hubs,
unpublished assignments, and same-day stack mismatches.

Never writes. Usage:
  python -m scripts.diagnose_practice_assignments
  python -m scripts.diagnose_practice_assignments --limit 50
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from app.practice.assignment_ledger import hub_ids_from_study_plan
from app.practice.invariants import validate_user_practice_invariants
from app.practice.repository import _exec, get_supabase


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--page-size", type=int, default=50)
    args = parser.parse_args()
    sb = get_supabase()

    profiles: list[dict[str, Any]] = []
    remaining = args.limit
    after = None
    while remaining > 0:
        lim = min(args.page_size, remaining)
        q = (
            sb.table("user_learning_profiles")
            .select("user_id, study_plan, plan_tier, exam_date")
            .order("user_id")
            .limit(lim)
        )
        if after:
            q = q.gt("user_id", after)
        rows = _exec(q).data or []
        if not rows:
            break
        profiles.extend(rows)
        after = rows[-1]["user_id"]
        remaining -= len(rows)
        if len(rows) < lim:
            break

    user_ids = [str(p["user_id"]) for p in profiles if p.get("user_id")]
    ledger_by_user: dict[str, list[dict[str, Any]]] = {uid: [] for uid in user_ids}
    progress_by_user: dict[str, list[dict[str, Any]]] = {uid: [] for uid in user_ids}
    if user_ids:
        for chunk_start in range(0, len(user_ids), 100):
            chunk = user_ids[chunk_start : chunk_start + 100]
            led = (
                _exec(
                    sb.table("user_practice_assignments")
                    .select("user_id, hub_id, practice_set_id, skill")
                    .in_("user_id", chunk)
                )
            ).data or []
            for row in led:
                ledger_by_user.setdefault(str(row.get("user_id")), []).append(row)
            prog = (
                _exec(
                    sb.table("user_hub_progress")
                    .select("user_id, hub_id, status")
                    .in_("user_id", chunk)
                )
            ).data or []
            for row in prog:
                progress_by_user.setdefault(str(row.get("user_id")), []).append(row)

    hub_ids: set[str] = set()
    for rows in ledger_by_user.values():
        for row in rows:
            if row.get("hub_id"):
                hub_ids.add(str(row["hub_id"]))
    for p in profiles:
        hub_ids.update(
            hub_ids_from_study_plan(
                p.get("study_plan") if isinstance(p.get("study_plan"), dict) else {}
            )
        )

    hub_meta: dict[str, dict[str, Any]] = {}
    hub_to_set: dict[str, str] = {}
    ids = [h for h in hub_ids if h]
    for i in range(0, len(ids), 100):
        chunk = ids[i : i + 100]
        rows = (
            _exec(
                sb.table("practice_hubs")
                .select(
                    "id, set_id, submit_config, "
                    "practice_sets(id, status, practice_banks(skill, bank_number))"
                )
                .in_("id", chunk)
            )
        ).data or []
        for row in rows:
            hid = str(row.get("id") or "")
            sets = row.get("practice_sets") or {}
            if isinstance(sets, list):
                sets = sets[0] if sets else {}
            status = str(sets.get("status") or "")
            hub_meta[hid] = {
                **row,
                "status": status,
                "set_status": status,
                "set_id": str(row.get("set_id") or sets.get("id") or ""),
            }
            if row.get("set_id"):
                hub_to_set[hid] = str(row["set_id"])

    all_issues = []
    for profile in profiles:
        uid = str(profile.get("user_id") or "")
        plan = profile.get("study_plan") if isinstance(profile.get("study_plan"), dict) else {}
        issues = validate_user_practice_invariants(
            user_id=uid,
            ledger_rows=ledger_by_user.get(uid) or [],
            study_plan=plan,
            progress_rows=progress_by_user.get(uid) or [],
            hub_to_set=hub_to_set,
            hub_meta=hub_meta,
        )
        all_issues.extend(issue.as_dict() for issue in issues)

    counts: dict[str, int] = {}
    for issue in all_issues:
        counts[issue["kind"]] = counts.get(issue["kind"], 0) + 1
    report = {
        "users_scanned": len(profiles),
        "issue_count": len(all_issues),
        "counts": counts,
        "issues": all_issues,
    }
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 1 if all_issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
