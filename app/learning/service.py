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
    )
    return rebuilt.model_dump(mode="json")


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
    today = today or date.today()
    today_s = today.isoformat()
    raw_tasks: list[StudyTask] = []
    for week in study_plan.get("weeks") or []:
        if not isinstance(week, dict):
            continue
        for day in week.get("days") or []:
            if not isinstance(day, dict):
                continue
            if day.get("date") == today_s:
                for t in day.get("tasks") or []:
                    if isinstance(t, dict):
                        raw_tasks.append(StudyTask.model_validate(t))
                break
        if raw_tasks:
            break

    if not raw_tasks or user_id is None:
        return raw_tasks

    try:
        from app.practice.service import current_hub_id_for_skill
        from app.practice import repository as practice_repo

        progress = (
            progress_map
            if progress_map is not None
            else practice_repo.get_user_progress_map(user_id)
        )
        grouped = hubs_by_skill
    except Exception:
        logger.exception("todays_tasks hub rewrite failed for %s", user_id)
        return raw_tasks

    hub_by_skill: dict[str, str | None] = {}
    rewritten: list[StudyTask] = []
    for task in raw_tasks:
        skill = str(task.module or "").strip().lower()
        if skill not in hub_by_skill:
            try:
                hub_by_skill[skill] = current_hub_id_for_skill(
                    user_id=user_id,
                    skill=skill,
                    progress_map=progress,
                    hub_rows=(grouped.get(skill) if grouped is not None else None),
                )
            except Exception:
                hub_by_skill[skill] = task.hub_id
        rewritten.append(_rewrite_plan_task_href(task, hub_id=hub_by_skill.get(skill)))
    return rewritten


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
        study_plan=StudyPlan.model_validate(study_plan_raw),
        weekly_goals=weekly_goals,
        source_counts=SourceCounts.model_validate(row.get("source_counts") or {}),
        refreshed_at=_parse_dt(row.get("refreshed_at")),
        plan_week_start=_parse_date(row.get("plan_week_start")),
        todays_tasks=_todays_tasks(
            study_plan_raw,
            user_id=user_uuid,
            progress_map=progress_map,
            hubs_by_skill=hubs_by_skill,
        ),
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
        from app.learning.rules import build_recommendations, build_weekly_goals

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
    if _needs_refresh(row, force=force) or _diagnostic_uncounted(row, user_id):
        row = refresh_profile(user_id)
    assert row is not None
    response = row_to_response(row)
    # Short TTL collapses Strict Mode / layout+page duplicate assemble work.
    set_json(
        cache_key,
        response.model_dump(mode="json"),
        8,
    )
    return response


def invalidate_learning_profile_cache(user_id: UUID | str) -> None:
    from app.cache.hybrid_cache import delete_many

    delete_many([f"learning:profile:{user_id}"])


def update_task_status(user_id: UUID, task_id: str, status: str) -> StudyPlan:
    """Patch one task status and return the updated study_plan only (fast path)."""
    row = fetch_profile_row(user_id)
    if row is None:
        row = refresh_profile(user_id)

    study_plan = row.get("study_plan") or {}
    if not isinstance(study_plan, dict):
        study_plan = {}

    found = False
    weeks = list(study_plan.get("weeks") or [])
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
        from fastapi import HTTPException

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
    # Avoid row_to_response (hub rewrite + progress) — PATCH only needs study_plan.
    return StudyPlan.model_validate(study_plan)


def schedule_profile_refresh(user_id: UUID) -> None:
    """Best-effort background refresh (does not block the request)."""

    def _run() -> None:
        try:
            refresh_profile(user_id)
        except Exception:
            logger.exception("learning profile refresh failed for %s", user_id)

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

    completed_by_skill: dict[str, int] = {}
    try:
        from app.practice.service import hub_progress_map

        for skill, prog in hub_progress_map(user_id).items():
            completed_by_skill[skill] = int(prog.completed_count)
    except Exception:
        logger.exception("could not load hub progress for plan generation %s", user_id)

    plan_kwargs = dict(
        bands=bands,
        target=target_f,
        exam_date=exam_date,
        prep_start=prep_start,
        plan_tier=plan_tier,
        diagnostic_attempt_id=str(attempt.get("id") or ""),
        completed_by_skill=completed_by_skill,
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

    sources = load_all_sources(user_id)
    aggregate = build_aggregate(sources)
    from app.learning.rules import build_recommendations, build_weekly_goals

    recommendations = build_recommendations(aggregate)
    weekly_goals = build_weekly_goals(aggregate, recommendations)
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
        "recommendations": [r.model_dump() for r in recommendations],
        "study_plan": study_plan.model_dump(mode="json"),
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

    if rows:
        return row_to_response(rows[0])
    row = fetch_profile_row(user_id)
    if row is None:
        raise RuntimeError("failed to persist personalized study plan")
    return row_to_response(row)


def schedule_personalized_plan_generation(user_id: UUID) -> None:
    """Best-effort background personalized plan generation after payment."""

    def _run() -> None:
        try:
            generate_personalized_plan(user_id)
        except Exception:
            logger.exception("personalized plan generation failed for %s", user_id)

    threading.Thread(
        target=_run,
        daemon=True,
        name=f"learning-plan-gen-{user_id}",
    ).start()
