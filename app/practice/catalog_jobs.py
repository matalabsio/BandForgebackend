"""Publish fan-out: offer a newly published Question Bank set to active plans.

An S5 event only attempts S5. It never runs the generic unused picker.
"""

from __future__ import annotations

import logging
import random
import threading
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from app.db.supabase_client import execute_with_retry, get_supabase
from app.learning.service import (
    FULL_SKILL_PROGRAM_TIER,
    _has_active_personalized_plan,
    fetch_profile_row,
    invalidate_learning_profile_cache,
)
from app.practice.assignment import collect_used_assignment_ids
from app.practice.assignment_ledger import (
    hub_ids_from_study_plan,
    try_claim_practice_assignment,
)
from app.practice.repository import SKILLS, _exec, get_user_progress_map

logger = logging.getLogger(__name__)

JOB_TYPE = "practice.catalog_changed"
DEFAULT_USER_BATCH = 50


def _parse_day(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _task_hub(task: dict[str, Any]) -> str | None:
    hid = str(task.get("hub_id") or "").strip()
    return hid or None


def enqueue_catalog_changed(
    *,
    practice_set_id: UUID | str,
    hub_id: UUID | str,
    skill: str,
    reason: str = "published",
) -> str | None:
    """Insert or revive a durable practice.catalog_changed job. Returns job id."""
    skill_n = str(skill or "").strip().lower()
    if skill_n not in SKILLS:
        return None
    sb = get_supabase()
    result = _exec(
        sb.rpc(
            "enqueue_practice_catalog_changed",
            {
                "p_practice_set_id": str(practice_set_id),
                "p_hub_id": str(hub_id),
                "p_skill": skill_n,
                "p_reason": str(reason or "published"),
            },
        )
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else None
    return str(data) if data else None


def schedule_catalog_job_processing() -> None:
    """Best-effort in-process claim after enqueue; the leased worker is authoritative."""

    def _run() -> None:
        try:
            run_once()
        except Exception:
            logger.exception("practice catalog job daemon failed")

    threading.Thread(
        target=_run, daemon=True, name="practice-catalog-changed"
    ).start()


def list_eligible_plan_user_ids(
    *,
    after_user_id: str | None = None,
    limit: int = DEFAULT_USER_BATCH,
) -> list[str]:
    """Keyset page of entitled users with an active personalized plan."""
    lim = max(1, min(int(limit), 200))
    sb = get_supabase()
    try:
        params: dict[str, Any] = {"p_limit": lim}
        if after_user_id:
            params["p_after_user_id"] = after_user_id
        rows = _exec(sb.rpc("list_active_personalized_plan_users", params)).data or []
        out: list[str] = []
        for row in rows:
            if isinstance(row, dict):
                uid = str(row.get("user_id") or "").strip()
            else:
                uid = str(row or "").strip()
            if uid:
                out.append(uid)
        return out
    except Exception:
        logger.exception("list_active_personalized_plan_users rpc failed; using fallback")
        return _list_eligible_plan_user_ids_fallback(
            after_user_id=after_user_id, limit=lim
        )


def _list_eligible_plan_user_ids_fallback(
    *, after_user_id: str | None, limit: int
) -> list[str]:
    sb = get_supabase()
    today = date.today().isoformat()
    q = (
        sb.table("user_learning_profiles")
        .select("user_id, exam_date, plan_tier")
        .eq("plan_tier", FULL_SKILL_PROGRAM_TIER)
        .gte("exam_date", today)
        .order("user_id")
        .limit(limit)
    )
    if after_user_id:
        q = q.gt("user_id", after_user_id)
    rows = _exec(q).data or []
    ids = [str(r["user_id"]) for r in rows if r.get("user_id")]
    if not ids:
        return []
    now = datetime.now(UTC).isoformat()
    subs = (
        _exec(
            sb.table("subscriptions")
            .select("user_id, plans!inner(slug)")
            .eq("status", "active")
            .gt("expires_at", now)
            .in_("user_id", ids)
        )
    ).data or []
    entitled: set[str] = set()
    for row in subs:
        plans = row.get("plans") or {}
        if isinstance(plans, list):
            plans = plans[0] if plans else {}
        if isinstance(plans, dict) and plans.get("slug") == FULL_SKILL_PROGRAM_TIER:
            entitled.add(str(row.get("user_id") or ""))
    return [uid for uid in ids if uid in entitled]


def _iter_skill_days(study_plan: dict[str, Any], skill: str) -> list[dict[str, Any]]:
    days: list[dict[str, Any]] = []
    for week in study_plan.get("weeks") or []:
        if not isinstance(week, dict):
            continue
        for day in week.get("days") or []:
            if not isinstance(day, dict):
                continue
            if any(
                isinstance(t, dict)
                and str(t.get("module") or "").strip().lower() == skill
                for t in (day.get("tasks") or [])
            ):
                days.append(day)
    days.sort(key=lambda d: str(d.get("date") or ""))
    return days


def _existing_skill_hub(day: dict[str, Any], skill: str) -> str | None:
    for task in day.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        if str(task.get("module") or "").strip().lower() != skill:
            continue
        hid = _task_hub(task)
        if hid:
            return hid
    return None


def _day_kind(day_date: date | None, today: date) -> str:
    if day_date is None:
        return "future"
    if day_date < today:
        return "past"
    if day_date == today:
        return "today"
    return "future"


def find_eligible_empty_day(
    study_plan: dict[str, Any],
    *,
    skill: str,
    today: date,
) -> dict[str, Any] | None:
    """Earliest empty eligible day for this skill. Past and assigned days are skipped."""
    for day in _iter_skill_days(study_plan, skill):
        kind = _day_kind(_parse_day(day.get("date")), today)
        if kind == "past":
            continue
        if _existing_skill_hub(day, skill):
            continue
        return day
    return None


def _apply_hub_to_day(
    day: dict[str, Any],
    *,
    skill: str,
    hub_id: str,
    submit_config: dict[str, Any] | None = None,
) -> None:
    from app.learning.rules import _plan_open_href

    for task in day.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        if str(task.get("module") or "").strip().lower() != skill:
            continue
        task_type = str(task.get("task_type") or "practice")
        task["hub_id"] = hub_id
        task["href"] = _plan_open_href(
            skill=skill,
            hub_id=hub_id,
            task_type=task_type,
            task_id=str(task.get("id") or ""),
            submit_config=submit_config,
        )


def _set_on_plan_or_progress(
    *,
    study_plan: dict[str, Any],
    progress_map: dict[str, dict[str, Any]] | None,
    practice_set_id: str,
    hub_id: str,
) -> bool:
    """True when this set/hub is already on the calendar or in progress.

    Ledger-only rows are not treated as plan occupancy so a crash after claim
    but before persist can still fill the empty day on retry.
    """
    hid = str(hub_id)
    sid = str(practice_set_id)
    if hid in set(hub_ids_from_study_plan(study_plan)):
        return True
    if hid in (progress_map or {}):
        return True
    mapping = {hid: sid}
    _used_hubs, used_sets = collect_used_assignment_ids(
        user_id=None,
        study_plan=study_plan,
        progress_map=progress_map,
        hub_to_set=mapping,
    )
    return sid in used_sets


def _persist_plan(
    *,
    user_id: UUID | str,
    study_plan: dict[str, Any],
    expected_updated_at: str | None,
) -> bool:
    client = get_supabase()
    now = datetime.now(UTC).isoformat()
    q = (
        client.table("user_learning_profiles")
        .update({"study_plan": study_plan, "updated_at": now})
        .eq("user_id", str(user_id))
    )
    if expected_updated_at:
        q = q.eq("updated_at", expected_updated_at)
    rows = execute_with_retry(lambda: q.execute()).data or []
    return bool(rows)


def _repair_ledger_if_on_plan(
    *,
    user_id: UUID | str,
    hub_id: str,
    practice_set_id: str,
    skill: str,
    assigned_on: date | None,
) -> None:
    try:
        try_claim_practice_assignment(
            user_id=user_id,
            hub_id=hub_id,
            practice_set_id=practice_set_id,
            skill=skill,
            source="publish_fill",
            assigned_on=assigned_on,
        )
    except Exception:
        logger.exception(
            "ledger repair failed user=%s set=%s", user_id, practice_set_id
        )


def _set_exam_module(practice_set_id: str) -> str | None:
    """Read practice_sets.exam_module for fan-out gating (Writing only)."""
    try:
        rows = _exec(
            get_supabase()
            .table("practice_sets")
            .select("exam_module")
            .eq("id", str(practice_set_id))
            .limit(1)
        ).data or []
        if not rows:
            return None
        raw = rows[0].get("exam_module")
        if raw is None:
            return None
        text = str(raw).strip().lower()
        return text or None
    except Exception:
        logger.exception("set exam_module lookup failed set=%s", practice_set_id)
        return None


def offer_published_set(
    *,
    user_id: UUID | str,
    practice_set_id: str,
    hub_id: str,
    skill: str,
    today: date | None = None,
    profile_row: dict[str, Any] | None = None,
    submit_config: dict[str, Any] | None = None,
    persist_attempts: int = 3,
    set_exam_module: str | None = None,
    user_exam_module: str | None = None,
) -> str:
    """Offer this exact published set to one user. Never picks a different set."""
    today_d = today or date.today()
    skill_n = str(skill or "").strip().lower()
    set_id = str(practice_set_id)
    hid = str(hub_id)
    try:
        # Writing-only: require users.exam_module match before assigning.
        if skill_n == "writing":
            from app.practice.writing_track import (
                fsp_writing_track_ready,
                writing_set_compatible_with_user,
            )

            track = user_exam_module
            if track is None:
                try:
                    from app.payments.repository import get_user_exam_module

                    track = get_user_exam_module(user_id)
                except Exception:
                    track = None
            if not fsp_writing_track_ready(track):
                return "needs_writing_track"
            set_mod = set_exam_module
            if set_mod is None:
                set_mod = _set_exam_module(set_id)
            if not writing_set_compatible_with_user(
                set_exam_module=set_mod,
                user_exam_module=track,
            ):
                return "ineligible"

        row = (
            profile_row
            if profile_row is not None
            else fetch_profile_row(UUID(str(user_id)))
        )
        if not _has_active_personalized_plan(row):
            return "ineligible"
        plan = row.get("study_plan") if isinstance(row.get("study_plan"), dict) else {}
        if not plan:
            return "ineligible"
        try:
            progress = get_user_progress_map(UUID(str(user_id)))
        except Exception:
            progress = {}
        if _set_on_plan_or_progress(
            study_plan=plan,
            progress_map=progress,
            practice_set_id=set_id,
            hub_id=hid,
        ):
            _repair_ledger_if_on_plan(
                user_id=user_id,
                hub_id=hid,
                practice_set_id=set_id,
                skill=skill_n,
                assigned_on=_parse_day(plan.get("prep_start")) or today_d,
            )
            return "already_had_set"

        empty = find_eligible_empty_day(plan, skill=skill_n, today=today_d)
        if empty is None:
            return "no_capacity"

        claimed = False
        attempts = max(1, int(persist_attempts))
        for _ in range(attempts):
            assigned_on = _parse_day(empty.get("date")) or today_d
            if not claimed:
                status = try_claim_practice_assignment(
                    user_id=user_id,
                    hub_id=hid,
                    practice_set_id=set_id,
                    skill=skill_n,
                    source="publish_fill",
                    assigned_on=assigned_on,
                )
                if status == "conflict":
                    return "claim_conflict"
                if status not in ("claimed", "already"):
                    return "claim_conflict"
                claimed = True

            latest = fetch_profile_row(UUID(str(user_id))) or row
            if not _has_active_personalized_plan(latest):
                return "ineligible"
            plan = (
                latest.get("study_plan")
                if isinstance(latest.get("study_plan"), dict)
                else {}
            )
            if _set_on_plan_or_progress(
                study_plan=plan,
                progress_map=progress,
                practice_set_id=set_id,
                hub_id=hid,
            ):
                return "already_had_set"
            empty = find_eligible_empty_day(plan, skill=skill_n, today=today_d)
            if empty is None:
                return "no_capacity"
            _apply_hub_to_day(
                empty, skill=skill_n, hub_id=hid, submit_config=submit_config
            )
            assigned = list(plan.get("assigned_hub_ids") or [])
            if hid not in assigned:
                assigned.append(hid)
            plan["assigned_hub_ids"] = assigned
            expected = str(latest.get("updated_at") or "") or None
            if _persist_plan(
                user_id=user_id, study_plan=plan, expected_updated_at=expected
            ):
                invalidate_learning_profile_cache(user_id)
                return "filled"
        return "failed"
    except Exception:
        logger.exception("offer_published_set failed user=%s set=%s", user_id, set_id)
        return "failed"


def _next_attempt_at(attempt: int) -> str:
    base = min(1800, 20 * (2 ** max(0, attempt - 1)))
    delay = base + random.uniform(0, base * 0.25)
    return (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()


def _leased_update(row: dict[str, Any], values: dict[str, Any]) -> bool:
    result = (
        get_supabase()
        .table("practice_jobs")
        .update({**values, "updated_at": datetime.now(UTC).isoformat()})
        .eq("id", str(row["id"]))
        .eq("status", "processing")
        .eq("lease_token", str(row.get("lease_token") or ""))
        .execute()
    )
    return bool(result.data)


def mark_job_done(row: dict[str, Any], result: dict[str, Any]) -> bool:
    return _leased_update(row, {"status": "done", "result": result, "last_error": None})


def mark_job_retry(row: dict[str, Any], *, error: str, result: dict[str, Any] | None) -> bool:
    attempts = int(row.get("attempts") or 0)
    max_attempts = int(row.get("max_attempts") or 8)
    terminal = attempts >= max_attempts
    return _leased_update(
        row,
        {
            "status": "failed" if terminal else "retry",
            "last_error": error[:500],
            "result": result,
            "next_attempt_at": None if terminal else _next_attempt_at(attempts),
            "lease_token": None,
            "lease_expires_at": None,
        },
    )


def _set_is_published(practice_set_id: str) -> bool:
    rows = (
        _exec(
            get_supabase()
            .table("practice_sets")
            .select("status")
            .eq("id", str(practice_set_id))
            .limit(1)
        )
    ).data or []
    if not rows:
        return False
    return str(rows[0].get("status") or "").strip().lower() == "published"


def _hub_matches_published_set(hub_id: str, practice_set_id: str) -> bool:
    rows = (
        _exec(
            get_supabase()
            .table("practice_hubs")
            .select("id, set_id")
            .eq("id", str(hub_id))
            .limit(1)
        )
    ).data or []
    if not rows:
        return False
    return str(rows[0].get("set_id") or "") == str(practice_set_id)


def process_catalog_changed(
    payload: dict[str, Any],
    *,
    user_ids: list[str] | None = None,
    user_batch_size: int = DEFAULT_USER_BATCH,
    today: date | None = None,
    list_users=None,
    offer=None,
    set_is_published: bool | None = None,
    hub_matches_set: bool | None = None,
) -> dict[str, Any]:
    """Fan out one published set. Paginated; one user failure does not abort others."""
    started = datetime.now(UTC)
    skill = str(payload.get("skill") or "").strip().lower()
    set_id = str(payload.get("practice_set_id") or "")
    hub_id = str(payload.get("hub_id") or "")
    reason = str(payload.get("reason") or "published")
    stats = {
        "practice_set_id": set_id,
        "hub_id": hub_id,
        "skill": skill,
        "reason": reason,
        "users_scanned": 0,
        "users_filled": 0,
        "users_already_had_set": 0,
        "users_no_capacity": 0,
        "users_ineligible": 0,
        "users_needs_writing_track": 0,
        "claim_conflicts": 0,
        "persistence_failures": 0,
    }
    if reason != "published" or skill not in SKILLS or not set_id or not hub_id:
        stats["skipped"] = True
        stats["duration_ms"] = 0
        return stats
    if set_is_published is None and hub_matches_set is None:
        published = _set_is_published(set_id)
        hub_ok = _hub_matches_published_set(hub_id, set_id)
    else:
        published = True if set_is_published is None else bool(set_is_published)
        hub_ok = True if hub_matches_set is None else bool(hub_matches_set)
    if not published or not hub_ok:
        stats["skipped"] = True
        stats["skip_reason"] = (
            "unpublished" if not published else "invalid_hub"
        )
        stats["duration_ms"] = int(
            (datetime.now(UTC) - started).total_seconds() * 1000
        )
        logger.info(
            "practice.catalog_changed skipped set=%s skill=%s reason=%s",
            set_id,
            skill,
            stats["skip_reason"],
        )
        return stats

    offer_fn = offer or offer_published_set
    list_fn = list_users or list_eligible_plan_user_ids
    writing_set_module: str | None = None
    if skill == "writing" and offer is None:
        writing_set_module = _set_exam_module(set_id)
    after: str | None = None
    pages = 0
    while True:
        pages += 1
        if user_ids is not None:
            batch = user_ids if pages == 1 else []
        else:
            batch = list_fn(after_user_id=after, limit=user_batch_size)
        if not batch:
            break
        after = batch[-1]
        for uid in batch:
            stats["users_scanned"] += 1
            try:
                if skill == "writing" and offer is None:
                    outcome = offer_fn(
                        user_id=uid,
                        practice_set_id=set_id,
                        hub_id=hub_id,
                        skill=skill,
                        today=today,
                        set_exam_module=writing_set_module,
                    )
                else:
                    outcome = offer_fn(
                        user_id=uid,
                        practice_set_id=set_id,
                        hub_id=hub_id,
                        skill=skill,
                        today=today,
                    )
            except Exception:
                logger.exception("catalog_changed user failed user=%s", uid)
                outcome = "failed"
            if outcome == "filled":
                stats["users_filled"] += 1
            elif outcome == "already_had_set":
                stats["users_already_had_set"] += 1
            elif outcome == "no_capacity":
                stats["users_no_capacity"] += 1
            elif outcome == "ineligible":
                stats["users_ineligible"] += 1
            elif outcome == "needs_writing_track":
                stats["users_needs_writing_track"] += 1
            elif outcome == "claim_conflict":
                stats["claim_conflicts"] += 1
            else:
                stats["persistence_failures"] += 1
        if user_ids is not None:
            break
        if len(batch) < user_batch_size:
            break

    stats["duration_ms"] = int(
        (datetime.now(UTC) - started).total_seconds() * 1000
    )
    logger.info(
        "practice.catalog_changed set=%s skill=%s scanned=%s filled=%s "
        "already=%s no_capacity=%s ineligible=%s needs_track=%s conflicts=%s "
        "failed=%s ms=%s",
        set_id,
        skill,
        stats["users_scanned"],
        stats["users_filled"],
        stats["users_already_had_set"],
        stats["users_no_capacity"],
        stats["users_ineligible"],
        stats["users_needs_writing_track"],
        stats["claim_conflicts"],
        stats["persistence_failures"],
        stats["duration_ms"],
    )
    try:
        from app.reliability.metrics import incr, record_event

        incr("practice.catalog_changed", amount=1)
        incr("practice.catalog_changed.filled", amount=stats["users_filled"])
        incr("practice.catalog_changed.already_had_set", amount=stats["users_already_had_set"])
        incr("practice.catalog_changed.no_capacity", amount=stats["users_no_capacity"])
        incr("practice.catalog_changed.ineligible", amount=stats["users_ineligible"])
        incr("practice.catalog_changed.claim_conflicts", amount=stats["claim_conflicts"])
        incr("practice.catalog_changed.failed", amount=stats["persistence_failures"])
        record_event(
            "practice.catalog_changed",
            detail=f"skill={skill}",
            meta={k: stats[k] for k in stats if k != "hub_id"},
        )
    except Exception:
        pass
    return stats


def process_job_row(row: dict[str, Any], *, user_batch_size: int = DEFAULT_USER_BATCH) -> dict[str, Any]:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    try:
        stats = process_catalog_changed(payload, user_batch_size=user_batch_size)
    except Exception as exc:
        logger.exception("practice.catalog_changed crashed job=%s", row.get("id"))
        mark_job_retry(row, error=f"worker_exception:{type(exc).__name__}", result=None)
        raise
    if int(stats.get("persistence_failures") or 0) > 0:
        mark_job_retry(
            row,
            error=f"persistence_failures={stats['persistence_failures']}",
            result=stats,
        )
    else:
        mark_job_done(row, stats)
    return stats


def claim_jobs(*, batch_size: int = 5, lease_seconds: int = 300) -> list[dict[str, Any]]:
    result = get_supabase().rpc(
        "claim_practice_jobs",
        {"p_batch_size": batch_size, "p_lease_seconds": lease_seconds},
    ).execute()
    return list(result.data or [])


def run_once(*, user_batch_size: int | None = None) -> int:
    from app.config import get_settings

    settings = get_settings()
    batch = int(getattr(settings, "practice_job_batch_size", 5) or 5)
    lease = int(getattr(settings, "practice_job_lease_seconds", 300) or 300)
    users = int(
        user_batch_size
        or getattr(settings, "practice_job_user_batch_size", DEFAULT_USER_BATCH)
        or DEFAULT_USER_BATCH
    )
    rows = claim_jobs(batch_size=batch, lease_seconds=lease)
    for row in rows:
        try:
            process_job_row(row, user_batch_size=users)
        except Exception:
            logger.exception("practice job failed id=%s", row.get("id"))
            try:
                mark_job_retry(row, error="worker_exception", result=None)
            except Exception:
                pass
    return len(rows)


def healthcheck(*, ping: bool = False) -> dict[str, Any]:
    """Lightweight worker startup check. Never claims a job."""
    info: dict[str, Any] = {
        "ok": True,
        "job_type": JOB_TYPE,
        "module": "app.practice.catalog_jobs",
    }
    if not ping:
        return info
    try:
        rows = (
            get_supabase()
            .table("practice_jobs")
            .select("id")
            .limit(1)
            .execute()
        )
        info["practice_jobs_reachable"] = True
        info["sample"] = bool(rows.data)
    except Exception as exc:
        info["ok"] = False
        info["practice_jobs_reachable"] = False
        info["error"] = type(exc).__name__
    return info


def run_forever() -> None:
    from app.config import get_settings

    poll = float(getattr(get_settings(), "practice_job_poll_seconds", 2.0) or 2.0)
    while True:
        n = run_once()
        if n == 0:
            import time

            time.sleep(max(0.5, poll))


def main() -> None:
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Startup/health check: import worker, optionally ping practice_jobs.",
    )
    parser.add_argument(
        "--ping",
        action="store_true",
        help="With --check, SELECT practice_jobs (does not claim a job).",
    )
    args = parser.parse_args()
    if args.check:
        info = healthcheck(ping=args.ping)
        print(info)
        if not info.get("ok"):
            raise SystemExit(1)
        return
    if args.once:
        run_once()
        return
    run_forever()


if __name__ == "__main__":
    main()
