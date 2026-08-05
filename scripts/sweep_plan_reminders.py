#!/usr/bin/env python3
"""Enqueue learning.daily_reminder emails for entitled users with unfinished Today tasks.

Uses the existing notification_outbox + worker (Resend). Idempotent per user + IST date.

Run once (daily cron, e.g. 07:00 IST):
  cd backend && PYTHONPATH=. python scripts/sweep_plan_reminders.py

See railway.toml and scripts/run_notification_worker.sh for the always-on delivery worker.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# Allow `python scripts/sweep_plan_reminders.py` from backend/
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.db.supabase_client import get_supabase  # noqa: E402
from app.notifications import repository  # noqa: E402

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
EVENT_TYPE = "learning.daily_reminder"
FULL_SKILL_SLUG = "full_skill_program"
PAGE = 200


def today_ist() -> str:
    return datetime.now(IST).date().isoformat()


def _unfinished_today_tasks(
    study_plan: dict[str, Any] | None, *, today: str
) -> list[dict[str, Any]]:
    if not isinstance(study_plan, dict):
        return []
    for week in study_plan.get("weeks") or []:
        if not isinstance(week, dict):
            continue
        for day in week.get("days") or []:
            if not isinstance(day, dict):
                continue
            if day.get("date") != today:
                continue
            tasks = []
            for task in day.get("tasks") or []:
                if not isinstance(task, dict):
                    continue
                status = str(task.get("status") or "pending").lower()
                if status in ("done", "skipped"):
                    continue
                tasks.append(task)
            return tasks
    return []


def _active_fsp_user_ids(*, now_iso: str) -> list[str]:
    sb = get_supabase()
    user_ids: list[str] = []
    offset = 0
    while True:
        result = (
            sb.table("subscriptions")
            .select("user_id, plans!inner(slug)")
            .eq("status", "active")
            .gt("expires_at", now_iso)
            .eq("plans.slug", FULL_SKILL_SLUG)
            .range(offset, offset + PAGE - 1)
            .execute()
        )
        rows = result.data or []
        for row in rows:
            uid = row.get("user_id")
            if uid:
                user_ids.append(str(uid))
        if len(rows) < PAGE:
            break
        offset += PAGE
    # Deduplicate while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for uid in user_ids:
        if uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
    return out


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def sweep(*, dry_run: bool = False) -> dict[str, int]:
    today = today_ist()
    now_iso = datetime.now(UTC).isoformat()
    entitled = _active_fsp_user_ids(now_iso=now_iso)
    stats = {
        "entitled": len(entitled),
        "eligible_prefs": 0,
        "with_unfinished": 0,
        "enqueued": 0,
        "skipped_existing": 0,
        "skipped_no_email": 0,
    }
    if not entitled:
        return stats

    sb = get_supabase()
    for chunk in _chunked(entitled, PAGE):
        users = (
            sb.table("users")
            .select("id, email, full_name, plan_reminders_email, is_active")
            .in_("id", chunk)
            .eq("plan_reminders_email", True)
            .eq("is_active", True)
            .execute()
        ).data or []
        stats["eligible_prefs"] += len(users)
        by_id = {str(u["id"]): u for u in users if isinstance(u, dict) and u.get("id")}
        if not by_id:
            continue

        profiles = (
            sb.table("user_learning_profiles")
            .select("user_id, study_plan")
            .in_("user_id", list(by_id.keys()))
            .execute()
        ).data or []

        for profile in profiles:
            uid = str(profile.get("user_id") or "")
            user = by_id.get(uid)
            if not user:
                continue
            email = str(user.get("email") or "").strip()
            if not email:
                stats["skipped_no_email"] += 1
                continue
            unfinished = _unfinished_today_tasks(
                profile.get("study_plan") if isinstance(profile.get("study_plan"), dict) else None,
                today=today,
            )
            if not unfinished:
                continue
            stats["with_unfinished"] += 1
            if repository.already_enqueued_plan_reminder(user_id=uid, local_date=today):
                stats["skipped_existing"] += 1
                continue
            titles = [
                str(t.get("title") or t.get("label") or t.get("skill") or "Practice")
                for t in unfinished
            ]
            payload = {
                "student_name": (user.get("full_name") or "").strip() or None,
                "unfinished_count": len(unfinished),
                "task_titles": titles[:5],
                "local_date": today,
            }
            if dry_run:
                logger.info(
                    "dry_run would enqueue user=%s unfinished=%d",
                    uid,
                    len(unfinished),
                )
                stats["enqueued"] += 1
                continue
            if repository.enqueue_plan_reminder(
                user_id=uid,
                email=email,
                local_date=today,
                payload=payload,
            ):
                stats["enqueued"] += 1
            else:
                stats["skipped_existing"] += 1
    return stats


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    dry_run = "--dry-run" in sys.argv
    stats = sweep(dry_run=dry_run)
    logger.info(
        "sweep_plan_reminders done dry_run=%s entitled=%d eligible=%d unfinished=%d "
        "enqueued=%d skipped_existing=%d skipped_no_email=%d",
        dry_run,
        stats["entitled"],
        stats["eligible_prefs"],
        stats["with_unfinished"],
        stats["enqueued"],
        stats["skipped_existing"],
        stats["skipped_no_email"],
    )


if __name__ == "__main__":
    main()
