"""Persistence and refresh lifecycle for adaptive learning profiles."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from app.db.supabase_client import execute_with_retry, get_supabase
from app.learning.aggregate import build_aggregate
from app.learning.ingest import (
    diagnostic_bands_from_attempt,
    load_all_sources,
    load_diagnostic_seed,
    load_user_exam_and_target,
)
from app.learning.rules import (
    _plan_open_href,
    apply_plan_rules,
    build_personalized_study_plan,
    monday_of,
)
from app.learning.schemas import (
    GrammarStats,
    LearningProfileResponse,
    ModuleBandSummary,
    RecommendationItem,
    SkillHubProgress,
    SourceCounts,
    StudyPlan,
    StudyTask,
    VocabStats,
    WeaknessItem,
    WeeklyGoal,
)

logger = logging.getLogger(__name__)

REFRESH_MAX_AGE = timedelta(hours=24)
FULL_SKILL_PROGRAM_TIER = "full_skill_program"


def _personalized_plan_is_bloated(study_plan: dict[str, Any] | None) -> bool:
    """True when a day repeats the same skill's watch (old per-slot expansion)."""
    if not isinstance(study_plan, dict):
        return False
    for week in study_plan.get("weeks") or []:
        if not isinstance(week, dict):
            continue
        for day in week.get("days") or []:
            if not isinstance(day, dict):
                continue
            watch_counts: dict[str, int] = {}
            for task in day.get("tasks") or []:
                if not isinstance(task, dict):
                    continue
                if task.get("task_type") != "watch":
                    continue
                module = str(task.get("module") or "")
                watch_counts[module] = watch_counts.get(module, 0) + 1
                if watch_counts[module] > 1:
                    return True
    return False


def _bands_from_aggregate(aggregate: dict[str, Any]) -> dict[str, float | None]:
    summary = aggregate.get("module_summary") or {}
    out: dict[str, float | None] = {}
    for skill in ("listening", "reading", "writing", "speaking"):
        row = summary.get(skill) if isinstance(summary, dict) else None
        if isinstance(row, dict) and row.get("latest") is not None:
            try:
                val = float(row["latest"])
                out[skill] = val if val > 0 else None
            except (TypeError, ValueError):
                out[skill] = None
        else:
            out[skill] = None
    return out


def _target_from_row_or_aggregate(
    row: dict[str, Any] | None,
    aggregate: dict[str, Any],
) -> float:
    for source in (row or {}, aggregate):
        raw = source.get("target_band")
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return 7.0


def _rebuild_bloated_personalized_plan(
    *,
    prior: dict[str, Any],
    prior_plan: dict[str, Any],
    aggregate: dict[str, Any],
) -> dict[str, Any] | None:
    exam = _parse_date(prior.get("exam_date")) or _parse_date(prior_plan.get("exam_date"))
    prep = _parse_date(prior.get("prep_start")) or _parse_date(prior_plan.get("prep_start"))
    if exam is None or prep is None:
        return None
    rebuilt = build_personalized_study_plan(
        bands=_bands_from_aggregate(aggregate),
        target=_target_from_row_or_aggregate(prior, aggregate),
        exam_date=exam,
        prep_start=prep,
        plan_tier=FULL_SKILL_PROGRAM_TIER,
        diagnostic_attempt_id=(
            str(prior_plan.get("diagnostic_attempt_id"))
            if prior_plan.get("diagnostic_attempt_id")
            else None
        ),
        prior_plan=prior_plan,
        weak_tags_by_skill=_weak_tags_from_aggregate(aggregate),
    )
    return rebuilt.model_dump(mode="json")


def _weak_tags_from_aggregate(aggregate: dict[str, Any]) -> dict[str, list[str]]:
    from app.practice.weakness import weak_tags_from_profile

    return weak_tags_from_profile(list(aggregate.get("skill_weaknesses") or []))


def _prior_status_by_task_id(study_plan: dict[str, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(study_plan, dict):
        return out
    for week in study_plan.get("weeks") or []:
        if not isinstance(week, dict):
            continue
        for day in week.get("days") or []:
            if not isinstance(day, dict):
                continue
            for task in day.get("tasks") or []:
                if not isinstance(task, dict):
                    continue
                tid = task.get("id")
                st = task.get("status")
                if tid and st:
                    out[str(tid)] = str(st)
    return out


def _merge_remaining_plan(
    *,
    prior_plan: dict[str, Any],
    rebuilt: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    """Keep past days from prior_plan; use rebuilt for today→exam; merge statuses."""
    prior_status = _prior_status_by_task_id(prior_plan)
    past_days: dict[str, dict[str, Any]] = {}
    for week in prior_plan.get("weeks") or []:
        if not isinstance(week, dict):
            continue
        for day in week.get("days") or []:
            if not isinstance(day, dict):
                continue
            ds = str(day.get("date") or "")[:10]
            try:
                if date.fromisoformat(ds) < today:
                    past_days[ds] = day
            except ValueError:
                continue

    # Apply prior statuses onto rebuilt future tasks where ids still match
    new_weeks: list[dict[str, Any]] = []
    for week in rebuilt.get("weeks") or []:
        if not isinstance(week, dict):
            continue
        days_out: list[dict[str, Any]] = []
        for day in week.get("days") or []:
            if not isinstance(day, dict):
                continue
            ds = str(day.get("date") or "")[:10]
            try:
                d = date.fromisoformat(ds)
            except ValueError:
                days_out.append(day)
                continue
            if d < today and ds in past_days:
                days_out.append(past_days[ds])
                continue
            tasks_out = []
            for task in day.get("tasks") or []:
                if not isinstance(task, dict):
                    continue
                t = dict(task)
                tid = str(t.get("id") or "")
                if tid and tid in prior_status:
                    t["status"] = prior_status[tid]
                elif not t.get("status"):
                    t["status"] = "pending"
                tasks_out.append(t)
            days_out.append({**day, "tasks": tasks_out})
        new_weeks.append({**week, "days": days_out})

    merged = {**rebuilt, "weeks": new_weeks}
    # Preserve prep_start from prior
    if prior_plan.get("prep_start"):
        merged["prep_start"] = prior_plan["prep_start"]
    return merged


def _should_weekly_replan(row: dict[str, Any] | None) -> bool:
    """True when Monday rolled over or 7+ days since last_replan_at."""
    if not row or not _has_active_personalized_plan(row):
        return False
    today = date.today()
    this_monday = monday_of(today)
    plan_week = _parse_date(row.get("plan_week_start"))
    study_plan = row.get("study_plan") if isinstance(row.get("study_plan"), dict) else {}
    last_raw = study_plan.get("last_replan_at") if isinstance(study_plan, dict) else None
    last_replan_dt = _parse_dt(last_raw) if last_raw else None
    last_replan_d = last_replan_dt.date() if last_replan_dt else None

    if plan_week is not None and plan_week < this_monday:
        return True
    if last_replan_d is None:
        # Never replan'd — use plan_week_start or refreshed_at as baseline
        baseline = plan_week or (_parse_dt(row.get("refreshed_at")) or datetime.now(UTC)).date()
        return (today - baseline).days >= 7
    if monday_of(last_replan_d) < this_monday:
        return True
    return (today - last_replan_d).days >= 7


def _hub_progress_for_user(user_id: UUID) -> dict[str, SkillHubProgress]:
    try:
        from app.practice.service import hub_progress_map

        progress = hub_progress_map(user_id)
        return {
            skill: SkillHubProgress.model_validate(prog.model_dump())
            for skill, prog in progress.items()
        }
    except Exception:
        return {}


def _timeline_fields(
    row: dict[str, Any],
    study_plan_raw: dict[str, Any],
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    prep_start = _parse_date(row.get("prep_start")) or _parse_date(study_plan_raw.get("prep_start"))
    exam_date = _parse_date(row.get("exam_date")) or _parse_date(study_plan_raw.get("exam_date"))
    total_days = row.get("total_days")
    if total_days is None:
        total_days = study_plan_raw.get("total_days")
    try:
        total_days_i = int(total_days) if total_days is not None else None
    except (TypeError, ValueError):
        total_days_i = None

    skill_difficulty = row.get("skill_difficulty") or study_plan_raw.get("skill_difficulty") or {}
    if not isinstance(skill_difficulty, dict):
        skill_difficulty = {}

    current_day = None
    days_remaining = None
    if prep_start is not None and total_days_i is not None:
        current_day = min((today - prep_start).days + 1, total_days_i)
        current_day = max(current_day, 1)
    if exam_date is not None:
        days_remaining = max((exam_date - today).days, 0)

    return {
        "prep_start": prep_start,
        "exam_date": exam_date,
        "total_days": total_days_i,
        "current_day": current_day,
        "days_remaining": days_remaining,
        "skill_difficulty": skill_difficulty,
    }


def _has_active_personalized_plan(row: dict[str, Any] | None) -> bool:
    if row is None:
        return False
    plan_tier = row.get("plan_tier")
    study_plan = row.get("study_plan") if isinstance(row.get("study_plan"), dict) else {}
    if plan_tier != FULL_SKILL_PROGRAM_TIER and study_plan.get("plan_tier") != FULL_SKILL_PROGRAM_TIER:
        return False
    exam_date = _parse_date(row.get("exam_date")) or _parse_date(study_plan.get("exam_date"))
    if exam_date is None:
        return False
    return exam_date >= date.today()


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def _rewrite_plan_task_href(task: StudyTask, *, hub_id: str | None) -> StudyTask:
    """Point Today tasks at the current unlocked hub with plan-mode query params."""
    skill = str(task.module or "").strip().lower()
    task_type = task.task_type if task.task_type in ("watch", "practice", "submit") else "practice"
    if skill not in ("listening", "reading", "writing", "speaking"):
        return task
    if not hub_id:
        # Prefer disabled catalogue link over bare skill browse from Today
        return task.model_copy(
            update={
                "hub_id": None,
                "href": f"/study-plan/today?skill={skill}&unavailable=1",
            }
        )
    return task.model_copy(
        update={
            "hub_id": hub_id,
            "href": _plan_open_href(
                skill=skill,
                hub_id=hub_id,
                task_type=task_type,
                task_id=task.id,
            ),
        }
    )


def _todays_tasks(
    study_plan: dict[str, Any],
    today: date | None = None,
    *,
    user_id: UUID | None = None,
    progress_map: dict[str, dict[str, Any]] | None = None,
    hubs_by_skill: dict[str, list[dict[str, Any]]] | None = None,
) -> list[StudyTask]:
    """Return today's tasks from an already-rewritten study_plan (same engine as calendar)."""
    del user_id, progress_map, hubs_by_skill  # rewrite happens in row_to_response
    today = today or date.today()
    today_s = today.isoformat()
    for week in study_plan.get("weeks") or []:
        if not isinstance(week, dict):
            continue
        for day in week.get("days") or []:
            if not isinstance(day, dict):
                continue
            if day.get("date") == today_s:
                return [
                    StudyTask.model_validate(t)
                    for t in (day.get("tasks") or [])
                    if isinstance(t, dict)
                ]
    return []


def _progress_fingerprint(
    progress_map: dict[str, dict[str, Any]] | None,
    *,
    weak_tags_by_skill: dict[str, list[str]] | None = None,
) -> str:
    """Stable hash of completed hub ids (+ weak tags) for rewritten-plan cache keys."""
    import hashlib

    if not progress_map:
        completed_part = "empty"
    else:
        completed = sorted(
            hid
            for hid, row in progress_map.items()
            if isinstance(row, dict) and str(row.get("status") or "") == "completed"
        )
        completed_part = ",".join(completed)
    weak_part = ""
    if weak_tags_by_skill:
        bits = []
        for skill in sorted(weak_tags_by_skill.keys()):
            tags = ",".join(weak_tags_by_skill[skill] or [])
            bits.append(f"{skill}:{tags}")
        weak_part = "|".join(bits)
    raw = f"{completed_part}#{weak_part}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _serve_rewritten_study_plan(
    study_plan_raw: dict[str, Any],
    *,
    user_id: UUID,
    prep_start: date | None,
    progress_map: dict[str, dict[str, Any]] | None,
    skill_weaknesses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply soft-repeat (+ weakness-weighted) assignment so calendar + Today share hubs."""
    from app.cache.hybrid_cache import get_json, set_json
    from app.practice.weakness import weak_tags_from_profile

    weak_tags = weak_tags_from_profile(skill_weaknesses)
    fp = _progress_fingerprint(progress_map, weak_tags_by_skill=weak_tags)
    cache_key = f"learning:plan_rewritten:{user_id}:{fp}"
    cached = get_json(cache_key)
    if isinstance(cached, dict) and (
        cached.get("weeks") is not None or cached.get("weekly_focus") is not None
    ):
        return cached

    try:
        from app.practice.assignment import cursors_by_skill, rewrite_plan_hubs
        from app.practice.catalog import (
            get_hub_skill_tags_by_id,
            get_hub_submit_configs_by_id,
            get_ordered_hub_ids_by_skill,
        )

        ordered = get_ordered_hub_ids_by_skill()
        submit_by_hub = get_hub_submit_configs_by_id()
        hub_tags = get_hub_skill_tags_by_id() if weak_tags else None
        cursors = cursors_by_skill(
            user_id=user_id,
            progress_map=progress_map,
            ordered_ids=ordered,
        )

        def href_builder(
            *,
            skill: str,
            hub_id: str | None,
            task_type: str,
            task_id: str | None,
        ) -> str:
            if not hub_id:
                try:
                    from app.reliability.metrics import record_event

                    record_event(
                        "empty_hub_assignment",
                        detail=f"skill={skill}",
                        meta={"user_id": str(user_id), "skill": skill},
                    )
                except Exception:
                    pass
                return f"/study-plan/today?skill={skill}&unavailable=1"
            tt = task_type if task_type in ("watch", "practice", "submit") else "practice"
            cfg = submit_by_hub.get(str(hub_id)) or {}
            return _plan_open_href(
                skill=skill,
                hub_id=hub_id,
                task_type=tt,
                task_id=str(task_id or ""),
                submit_config=cfg if isinstance(cfg, dict) else None,
            )

        rewritten = rewrite_plan_hubs(
            study_plan_raw,
            cursors=cursors,
            prep_start=prep_start,
            ordered_ids=ordered,
            href_builder=href_builder,
            weak_tags_by_skill=weak_tags or None,
            hub_tags_by_id=hub_tags,
        )
        set_json(cache_key, rewritten, 60)
        return rewritten
    except Exception:
        logger.exception("rewrite_plan_hubs failed for %s", user_id)
        try:
            from app.reliability.metrics import record_event

            record_event(
                "planner_failure",
                detail="rewrite_plan_hubs",
                meta={"user_id": str(user_id)},
            )
        except Exception:
            pass
        return study_plan_raw


def row_to_response(row: dict[str, Any]) -> LearningProfileResponse:
    module_raw = row.get("module_summary") or {}
    module_summary = {
        k: ModuleBandSummary.model_validate(v)
        for k, v in module_raw.items()
        if isinstance(v, dict)
    }
    target = row.get("target_band")
    current = row.get("current_band")
    try:
        target_f = float(target) if target is not None else None
    except (TypeError, ValueError):
        target_f = None
    try:
        current_f = float(current) if current is not None else None
    except (TypeError, ValueError):
        current_f = None

    gap = None
    if target_f is not None and current_f is not None:
        gap = round((target_f - current_f) * 2) / 2

    study_plan_raw = row.get("study_plan") or {}
    if not isinstance(study_plan_raw, dict):
        study_plan_raw = {}

    weaknesses = [
        WeaknessItem.model_validate(w)
        for w in (row.get("top_weaknesses") or [])
        if isinstance(w, dict)
    ]
    recommendations = [
        RecommendationItem.model_validate(r)
        for r in (row.get("recommendations") or [])
        if isinstance(r, dict)
    ]
    weekly_goals = [
        WeeklyGoal.model_validate(g)
        for g in (row.get("weekly_goals") or [])
        if isinstance(g, dict)
    ]

    timeline = _timeline_fields(row, study_plan_raw)
    user_uuid = UUID(str(row["user_id"]))

    hub_progress: dict[str, SkillHubProgress] = {}
    progress_map: dict[str, dict[str, Any]] | None = None
    hubs_by_skill: dict[str, list[dict[str, Any]]] | None = None
    try:
        from app.practice.service import practice_profile_bundle

        hub_prog_raw, progress_map, hubs_by_skill = practice_profile_bundle(user_uuid)
        hub_progress = {
            skill: SkillHubProgress.model_validate(prog.model_dump())
            for skill, prog in hub_prog_raw.items()
        }
    except Exception:
        logger.exception("practice_profile_bundle failed for %s", user_uuid)
        hub_progress = _hub_progress_for_user(user_uuid)

    rewritten_plan = _serve_rewritten_study_plan(
        study_plan_raw,
        user_id=user_uuid,
        prep_start=timeline["prep_start"],
        progress_map=progress_map,
        skill_weaknesses=list(row.get("skill_weaknesses") or []),
    )

    todays = _todays_tasks(
        rewritten_plan,
        user_id=user_uuid,
        progress_map=progress_map,
        hubs_by_skill=hubs_by_skill,
    )
    try:
        from app.reliability.metrics import mark_tasks_assigned_once

        # Once per user/UTC-day; amount = tasks served so completion_rate stays meaningful.
        mark_tasks_assigned_once(str(user_uuid), amount=max(len(todays), 1))
    except Exception:
        pass

    return LearningProfileResponse(
        user_id=str(row["user_id"]),
        current_band=current_f,
        target_band=target_f,
        gap_to_target=gap,
        module_summary=module_summary,
        criterion_trends=row.get("criterion_trends") or {},
        skill_weaknesses=list(row.get("skill_weaknesses") or []),
        top_weaknesses=weaknesses,
        vocab_stats=VocabStats.model_validate(row.get("vocab_stats") or {}),
        grammar_stats=GrammarStats.model_validate(row.get("grammar_stats") or {}),
        recommendations=recommendations,
        study_plan=StudyPlan.model_validate(rewritten_plan),
        weekly_goals=weekly_goals,
        source_counts=SourceCounts.model_validate(row.get("source_counts") or {}),
        refreshed_at=_parse_dt(row.get("refreshed_at")),
        plan_week_start=_parse_date(row.get("plan_week_start")),
        todays_tasks=todays,
        prep_start=timeline["prep_start"],
        exam_date=timeline["exam_date"],
        total_days=timeline["total_days"],
        current_day=timeline["current_day"],
        days_remaining=timeline["days_remaining"],
        skill_difficulty=timeline["skill_difficulty"],
        hub_progress=hub_progress,
    )


def fetch_profile_row(user_id: UUID) -> dict[str, Any] | None:
    client = get_supabase()
    rows = execute_with_retry(
        lambda: (
            client.table("user_learning_profiles")
            .select("*")
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )
    ).data or []
    return rows[0] if rows else None


def _needs_refresh(row: dict[str, Any] | None, *, force: bool = False) -> bool:
    if force:
        return True
    if row is None:
        return True
    refreshed = _parse_dt(row.get("refreshed_at"))
    if refreshed is None:
        return True
    now = datetime.now(UTC)
    if now - refreshed > REFRESH_MAX_AGE:
        return True
    if _has_active_personalized_plan(row):
        study_plan = row.get("study_plan") if isinstance(row.get("study_plan"), dict) else {}
        if _personalized_plan_is_bloated(study_plan):
            return True
        return False
    plan_start = _parse_date(row.get("plan_week_start"))
    if plan_start is None or plan_start != monday_of(date.today()):
        return True
    return False


def refresh_profile(user_id: UUID) -> dict[str, Any]:
    """Recompute aggregates + rules and upsert the profile row."""
    prior = fetch_profile_row(user_id)
    sources = load_all_sources(user_id)
    aggregate = build_aggregate(sources)
    week_start = monday_of(date.today())
    prior_plan = prior.get("study_plan") if prior else None
    prior_week = _parse_date(prior.get("plan_week_start")) if prior else None

    keep_personalized = _has_active_personalized_plan(prior)
    if keep_personalized and isinstance(prior_plan, dict):
        from app.learning.rules import (
            apply_weekly_goal_completion,
            build_recommendations,
            build_weekly_goals,
        )

        recommendations = build_recommendations(aggregate)
        weekly_goals = build_weekly_goals(aggregate, recommendations)
        study_plan_out: dict[str, Any] = prior_plan
        if _personalized_plan_is_bloated(prior_plan):
            rebuilt = _rebuild_bloated_personalized_plan(
                prior=prior or {},
                prior_plan=prior_plan,
                aggregate=aggregate,
            )
            if rebuilt is not None:
                study_plan_out = rebuilt
        weekly_goals = apply_weekly_goal_completion(
            weekly_goals,
            study_plan=study_plan_out,
            source_counts=aggregate.get("source_counts") or {},
            week_start=week_start,
        )
        planned = {
            "recommendations": [r.model_dump() for r in recommendations],
            "weekly_goals": [g.model_dump() for g in weekly_goals],
            "study_plan": study_plan_out,
            "plan_week_start": prior.get("plan_week_start") or week_start.isoformat(),
        }
    else:
        planned = apply_plan_rules(
            aggregate,
            week_start=week_start,
            prior_study_plan=prior_plan if isinstance(prior_plan, dict) else None,
            prior_week_start=prior_week,
        )
        from app.learning.rules import apply_weekly_goal_completion
        from app.learning.schemas import WeeklyGoal

        goals = [
            WeeklyGoal.model_validate(g)
            for g in (planned.get("weekly_goals") or [])
            if isinstance(g, dict)
        ]
        goals = apply_weekly_goal_completion(
            goals,
            study_plan=planned.get("study_plan") if isinstance(planned.get("study_plan"), dict) else None,
            source_counts=aggregate.get("source_counts") or {},
            week_start=week_start,
        )
        planned = {
            **planned,
            "weekly_goals": [g.model_dump() for g in goals],
        }

    now = datetime.now(UTC)
    payload = {
        "user_id": str(user_id),
        "current_band": aggregate.get("current_band"),
        "target_band": aggregate.get("target_band"),
        "module_summary": aggregate.get("module_summary") or {},
        "criterion_trends": aggregate.get("criterion_trends") or {},
        "skill_weaknesses": aggregate.get("skill_weaknesses") or [],
        "top_weaknesses": aggregate.get("top_weaknesses") or [],
        "vocab_stats": aggregate.get("vocab_stats") or {},
        "grammar_stats": aggregate.get("grammar_stats") or {},
        "recommendations": planned["recommendations"],
        "study_plan": planned["study_plan"],
        "weekly_goals": planned["weekly_goals"],
        "source_counts": aggregate.get("source_counts") or {},
        "refreshed_at": now.isoformat(),
        "plan_week_start": planned["plan_week_start"],
        "updated_at": now.isoformat(),
    }
    if keep_personalized and prior:
        for key in ("prep_start", "exam_date", "total_days", "plan_tier", "skill_difficulty"):
            if prior.get(key) is not None:
                payload[key] = prior[key]
        rebuilt_plan = planned.get("study_plan")
        if isinstance(rebuilt_plan, dict) and rebuilt_plan.get("skill_difficulty"):
            payload["skill_difficulty"] = rebuilt_plan["skill_difficulty"]
        if isinstance(rebuilt_plan, dict) and rebuilt_plan.get("total_days") is not None:
            payload["total_days"] = rebuilt_plan["total_days"]

    client = get_supabase()
    if prior is None:
        payload["created_at"] = now.isoformat()
        rows = execute_with_retry(
            lambda: client.table("user_learning_profiles").insert(payload).execute()
        ).data or []
    else:
        rows = execute_with_retry(
            lambda: (
                client.table("user_learning_profiles")
                .update(payload)
                .eq("user_id", str(user_id))
                .execute()
            )
        ).data or []

    if rows:
        invalidate_learning_profile_cache(user_id)
        return rows[0]
    # Fallback re-fetch
    row = fetch_profile_row(user_id)
    if row is None:
        raise RuntimeError("failed to persist learning profile")
    invalidate_learning_profile_cache(user_id)
    return row


def _has_module_summary_bands(row: dict[str, Any]) -> bool:
    module_summary = row.get("module_summary") or {}
    if not isinstance(module_summary, dict):
        return False
    for key in ("listening", "reading", "writing", "speaking"):
        mod = module_summary.get(key) or {}
        if not isinstance(mod, dict):
            continue
        latest = mod.get("latest")
        if latest is not None:
            try:
                if float(latest) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _diagnostic_uncounted(row: dict[str, Any] | None, user_id: UUID) -> bool:
    """True when a completed diagnostic exists but the cached snapshot ignores it."""
    if row is None:
        return False
    source_counts = row.get("source_counts") or {}
    if not isinstance(source_counts, dict):
        source_counts = {}
    if int(source_counts.get("diagnostic") or 0) > 0:
        return False
    if _has_module_summary_bands(row):
        return False
    client = get_supabase()
    rows = execute_with_retry(
        lambda: (
            client.table("diagnostic_attempts")
            .select("id")
            .eq("user_id", str(user_id))
            .eq("status", "completed")
            .limit(1)
            .execute()
        )
    ).data or []
    return bool(rows)


def ensure_profile(user_id: UUID, *, force: bool = False) -> LearningProfileResponse:
    from app.cache.hybrid_cache import get_json, set_json

    cache_key = f"learning:profile:{user_id}"
    if not force:
        cached = get_json(cache_key)
        if isinstance(cached, dict) and cached.get("user_id"):
            try:
                return LearningProfileResponse.model_validate(cached)
            except Exception:
                pass

    row = fetch_profile_row(user_id)
    if _should_weekly_replan(row):
        try:
            return replan_remaining_schedule(user_id)
        except Exception:
            logger.exception("weekly replan failed for %s; falling back to refresh", user_id)
    if _needs_refresh(row, force=force) or _diagnostic_uncounted(row, user_id):
        row = refresh_profile(user_id)
    assert row is not None
    response = row_to_response(row)
    # Phase 4: 30s TTL; mutations invalidate via invalidate_learning_profile_cache.
    set_json(
        cache_key,
        response.model_dump(mode="json"),
        30,
    )
    return response


def ensure_today_bundle(user_id: UUID):
    """Slim Today payload — full weeks stay on /profile for calendar."""
    from app.learning.schemas import TodayBundleResponse

    profile = ensure_profile(user_id)
    return TodayBundleResponse(
        user_id=profile.user_id,
        todays_tasks=profile.todays_tasks,
        hub_progress=profile.hub_progress,
        prep_start=profile.prep_start,
        exam_date=profile.exam_date,
        total_days=profile.total_days,
        current_day=profile.current_day,
        days_remaining=profile.days_remaining,
        skill_difficulty=profile.skill_difficulty,
        current_band=profile.current_band,
        target_band=profile.target_band,
        gap_to_target=profile.gap_to_target,
    )


def invalidate_learning_profile_cache(user_id: UUID | str) -> None:
    from app.cache.hybrid_cache import delete_many, invalidate_prefix

    delete_many(
        [
            f"learning:profile:{user_id}",
            f"practice:progress:{user_id}",
            f"dashboard_streak:{user_id}",
            f"dashboard_streak:v2:{user_id}",
        ]
    )
    try:
        invalidate_prefix(f"learning:plan_rewritten:{user_id}:")
    except Exception:
        pass


def update_task_status(user_id: UUID, task_id: str, status: str) -> StudyPlan:
    """Patch one task status and return the updated study_plan only (fast path)."""
    from fastapi import HTTPException

    from app.learning.plan_day_access import (
        day_access_denial_detail,
        find_task_day,
        is_plan_day_accessible,
    )

    row = fetch_profile_row(user_id)
    if row is None:
        row = refresh_profile(user_id)

    study_plan = row.get("study_plan") or {}
    if not isinstance(study_plan, dict):
        study_plan = {}

    weeks = list(study_plan.get("weeks") or [])
    _task_day, day_date = find_task_day(weeks, task_id)
    if day_date is None:
        raise HTTPException(status_code=404, detail="Task not found")

    today = date.today().isoformat()
    exam_raw = study_plan.get("exam_date") or row.get("exam_date")
    exam_date = exam_raw if isinstance(exam_raw, str) else None
    if exam_date is None and hasattr(exam_raw, "isoformat"):
        exam_date = exam_raw.isoformat()

    if not is_plan_day_accessible(day_date, today, exam_date, weeks):
        raise HTTPException(
            status_code=400,
            detail=day_access_denial_detail(day_date, today, exam_date, weeks),
        )

    found = False
    new_weeks = []
    for week in weeks:
        if not isinstance(week, dict):
            new_weeks.append(week)
            continue
        days = []
        for day in week.get("days") or []:
            if not isinstance(day, dict):
                days.append(day)
                continue
            tasks = []
            for task in day.get("tasks") or []:
                if (
                    isinstance(task, dict)
                    and str(task.get("id")) == task_id
                    and not found
                ):
                    task = {**task, "status": status}
                    found = True
                tasks.append(task)
            days.append({**day, "tasks": tasks})
        new_weeks.append({**week, "days": days})

    if not found:
        raise HTTPException(status_code=404, detail="Task not found")

    study_plan = {**study_plan, "weeks": new_weeks}
    now = datetime.now(UTC)
    client = get_supabase()
    execute_with_retry(
        lambda: (
            client.table("user_learning_profiles")
            .update({"study_plan": study_plan, "updated_at": now.isoformat()})
            .eq("user_id", str(user_id))
            .execute()
        )
    )
    invalidate_learning_profile_cache(user_id)
    if status == "done":
        try:
            from app.reliability.metrics import incr

            incr("task_done")
        except Exception:
            pass
    # Avoid row_to_response (hub rewrite + progress) — PATCH only needs study_plan.
    return StudyPlan.model_validate(study_plan)


def schedule_profile_refresh(user_id: UUID) -> None:
    """Best-effort background refresh (does not block the request)."""

    def _run() -> None:
        try:
            refresh_profile(user_id)
            invalidate_learning_profile_cache(user_id)
        except Exception:
            logger.exception("learning profile refresh failed for %s", user_id)
            try:
                from app.reliability.metrics import record_event

                record_event(
                    "planner_failure",
                    detail="profile_refresh",
                    meta={"user_id": str(user_id)},
                )
            except Exception:
                pass

    threading.Thread(target=_run, daemon=True, name=f"learning-refresh-{user_id}").start()


def generate_personalized_plan(
    user_id: UUID,
    *,
    plan_tier: str = FULL_SKILL_PROGRAM_TIER,
) -> LearningProfileResponse:
    """Build and persist an exam-date-bound personalized study plan."""
    from fastapi import HTTPException

    user_row = load_user_exam_and_target(user_id)
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")

    exam_date = _parse_date(user_row.get("exam_date"))
    if exam_date is None:
        raise HTTPException(status_code=400, detail="Exam date is required before generating a study plan")

    target = user_row.get("target_band")
    try:
        target_f = float(target) if target is not None else 7.0
    except (TypeError, ValueError):
        target_f = 7.0

    diagnostic = load_diagnostic_seed(user_id)
    if not diagnostic or not isinstance(diagnostic.get("attempt"), dict):
        raise HTTPException(
            status_code=404,
            detail="A completed diagnostic is required before generating a study plan",
        )

    attempt = diagnostic["attempt"]
    bands = diagnostic_bands_from_attempt(attempt)
    prep_start = date.today()
    prior = fetch_profile_row(user_id)
    prior_plan = prior.get("study_plan") if prior and isinstance(prior.get("study_plan"), dict) else None

    sources = load_all_sources(user_id)
    aggregate = build_aggregate(sources)
    # Prefer live module bands when available for hub weakness weighting
    live_bands = _bands_from_aggregate(aggregate)
    for skill, val in live_bands.items():
        if val is not None:
            bands[skill] = val
    weak_tags = _weak_tags_from_aggregate(aggregate)

    completed_by_skill: dict[str, int] = {}
    try:
        from app.practice.assignment import cursors_by_skill

        completed_by_skill = cursors_by_skill(user_id=user_id)
    except Exception:
        logger.exception("could not load skill cursors for plan generation %s", user_id)

    plan_kwargs = dict(
        bands=bands,
        target=target_f,
        exam_date=exam_date,
        prep_start=prep_start,
        plan_tier=plan_tier,
        diagnostic_attempt_id=str(attempt.get("id") or ""),
        completed_by_skill=completed_by_skill,
        weak_tags_by_skill=weak_tags,
    )
    if prior_plan:
        prior_exam = _parse_date(prior.get("exam_date")) or _parse_date(prior_plan.get("exam_date"))
        prior_prep = _parse_date(prior.get("prep_start")) or _parse_date(prior_plan.get("prep_start"))
        if prior_exam == exam_date and prior_prep == prep_start and prior_plan.get("plan_tier") == plan_tier:
            study_plan = build_personalized_study_plan(**plan_kwargs, prior_plan=prior_plan)
        else:
            study_plan = build_personalized_study_plan(**plan_kwargs, prior_plan=None)
    else:
        study_plan = build_personalized_study_plan(**plan_kwargs, prior_plan=None)

    from app.learning.rules import (
        apply_weekly_goal_completion,
        build_recommendations,
        build_weekly_goals,
    )

    recommendations = build_recommendations(aggregate)
    weekly_goals = build_weekly_goals(aggregate, recommendations)
    weekly_goals = apply_weekly_goal_completion(
        weekly_goals,
        study_plan=study_plan.model_dump(mode="json"),
        source_counts=aggregate.get("source_counts") or {},
        week_start=monday_of(prep_start),
    )
    now = datetime.now(UTC)
    plan_dump = study_plan.model_dump(mode="json")
    plan_dump["last_replan_at"] = now.isoformat()

    payload = {
        "user_id": str(user_id),
        "current_band": aggregate.get("current_band"),
        "target_band": aggregate.get("target_band"),
        "module_summary": aggregate.get("module_summary") or {},
        "criterion_trends": aggregate.get("criterion_trends") or {},
        "skill_weaknesses": aggregate.get("skill_weaknesses") or [],
        "top_weaknesses": aggregate.get("top_weaknesses") or [],
        "vocab_stats": aggregate.get("vocab_stats") or {},
        "grammar_stats": aggregate.get("grammar_stats") or {},
        "recommendations": [r.model_dump() for r in recommendations],
        "study_plan": plan_dump,
        "weekly_goals": [g.model_dump() for g in weekly_goals],
        "source_counts": aggregate.get("source_counts") or {},
        "refreshed_at": now.isoformat(),
        "plan_week_start": monday_of(prep_start).isoformat(),
        "prep_start": prep_start.isoformat(),
        "exam_date": exam_date.isoformat(),
        "total_days": study_plan.total_days,
        "plan_tier": plan_tier,
        "skill_difficulty": study_plan.skill_difficulty,
        "updated_at": now.isoformat(),
    }

    client = get_supabase()
    if prior is None:
        payload["created_at"] = now.isoformat()
        rows = execute_with_retry(
            lambda: client.table("user_learning_profiles").insert(payload).execute()
        ).data or []
    else:
        rows = execute_with_retry(
            lambda: (
                client.table("user_learning_profiles")
                .update(payload)
                .eq("user_id", str(user_id))
                .execute()
            )
        ).data or []

    invalidate_learning_profile_cache(user_id)
    if rows:
        return row_to_response(rows[0])
    row = fetch_profile_row(user_id)
    if row is None:
        raise RuntimeError("failed to persist personalized study plan")
    return row_to_response(row)


def replan_remaining_schedule(user_id: UUID) -> LearningProfileResponse:
    """Rebuild today→exam days from updated bands/weaknesses; preserve past + prep_start."""
    from fastapi import HTTPException

    prior = fetch_profile_row(user_id)
    if prior is None or not _has_active_personalized_plan(prior):
        raise HTTPException(
            status_code=400,
            detail="An active personalized study plan is required before replan",
        )

    prior_plan = prior.get("study_plan") if isinstance(prior.get("study_plan"), dict) else {}
    prep_start = _parse_date(prior.get("prep_start")) or _parse_date(prior_plan.get("prep_start"))
    exam_date = _parse_date(prior.get("exam_date")) or _parse_date(prior_plan.get("exam_date"))
    if prep_start is None or exam_date is None:
        raise HTTPException(status_code=400, detail="Plan is missing prep_start or exam_date")

    sources = load_all_sources(user_id)
    aggregate = build_aggregate(sources)
    bands = _bands_from_aggregate(aggregate)
    # Fill missing bands from diagnostic if needed
    diagnostic = load_diagnostic_seed(user_id)
    if diagnostic and isinstance(diagnostic.get("attempt"), dict):
        seed = diagnostic_bands_from_attempt(diagnostic["attempt"])
        for skill, val in seed.items():
            if bands.get(skill) is None and val is not None:
                bands[skill] = val

    target_f = _target_from_row_or_aggregate(prior, aggregate)
    plan_tier = str(prior.get("plan_tier") or FULL_SKILL_PROGRAM_TIER)
    weak_tags = _weak_tags_from_aggregate(aggregate)

    completed_by_skill: dict[str, int] = {}
    try:
        from app.practice.assignment import cursors_by_skill

        completed_by_skill = cursors_by_skill(user_id=user_id)
    except Exception:
        logger.exception("could not load skill cursors for replan %s", user_id)

    rebuilt = build_personalized_study_plan(
        bands=bands,
        target=target_f,
        exam_date=exam_date,
        prep_start=prep_start,  # do NOT reset
        plan_tier=plan_tier,
        diagnostic_attempt_id=(
            str(prior_plan.get("diagnostic_attempt_id"))
            if prior_plan.get("diagnostic_attempt_id")
            else None
        ),
        prior_plan=None,
        completed_by_skill=completed_by_skill,
        weak_tags_by_skill=weak_tags,
    )
    rebuilt_dump = rebuilt.model_dump(mode="json")
    today = date.today()
    merged = _merge_remaining_plan(
        prior_plan=prior_plan,
        rebuilt=rebuilt_dump,
        today=today,
    )
    now = datetime.now(UTC)
    merged["last_replan_at"] = now.isoformat()
    merged["prep_start"] = prep_start.isoformat()

    from app.learning.rules import (
        apply_weekly_goal_completion,
        build_recommendations,
        build_weekly_goals,
    )

    recommendations = build_recommendations(aggregate)
    weekly_goals = build_weekly_goals(aggregate, recommendations)
    weekly_goals = apply_weekly_goal_completion(
        weekly_goals,
        study_plan=merged,
        source_counts=aggregate.get("source_counts") or {},
        week_start=monday_of(today),
    )

    payload = {
        "current_band": aggregate.get("current_band"),
        "target_band": aggregate.get("target_band"),
        "module_summary": aggregate.get("module_summary") or {},
        "criterion_trends": aggregate.get("criterion_trends") or {},
        "skill_weaknesses": aggregate.get("skill_weaknesses") or [],
        "top_weaknesses": aggregate.get("top_weaknesses") or [],
        "vocab_stats": aggregate.get("vocab_stats") or {},
        "grammar_stats": aggregate.get("grammar_stats") or {},
        "recommendations": [r.model_dump() for r in recommendations],
        "study_plan": merged,
        "weekly_goals": [g.model_dump() for g in weekly_goals],
        "source_counts": aggregate.get("source_counts") or {},
        "refreshed_at": now.isoformat(),
        "plan_week_start": monday_of(today).isoformat(),
        "prep_start": prep_start.isoformat(),
        "exam_date": exam_date.isoformat(),
        "total_days": rebuilt.total_days,
        "plan_tier": plan_tier,
        "skill_difficulty": rebuilt.skill_difficulty,
        "updated_at": now.isoformat(),
    }

    client = get_supabase()
    rows = execute_with_retry(
        lambda: (
            client.table("user_learning_profiles")
            .update(payload)
            .eq("user_id", str(user_id))
            .execute()
        )
    ).data or []
    invalidate_learning_profile_cache(user_id)
    if rows:
        return row_to_response(rows[0])
    row = fetch_profile_row(user_id)
    if row is None:
        raise RuntimeError("failed to persist replanned study plan")
    return row_to_response(row)


def schedule_personalized_plan_generation(user_id: UUID) -> None:
    """Best-effort background personalized plan generation after payment."""

    def _run() -> None:
        try:
            generate_personalized_plan(user_id)
        except Exception:
            logger.exception("personalized plan generation failed for %s", user_id)
            try:
                from app.reliability.metrics import record_event

                record_event(
                    "planner_failure",
                    detail="plan_generation",
                    meta={"user_id": str(user_id)},
                )
            except Exception:
                pass

    threading.Thread(
        target=_run,
        daemon=True,
        name=f"learning-plan-gen-{user_id}",
    ).start()
