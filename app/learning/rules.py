"""Deterministic recommendations, weekly goals, and study-plan generation."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from app.learning.plan_sequencing import (
    SKILL_LABEL,
    SKILL_ORDER,
    allocate_days,
    build_primary_focus_queue,
    build_session_sequence,
    classify_skills,
    focus_label,
    focus_skills_from_gaps,
    gap_map,
)
from app.learning.schemas import (
    RecommendationItem,
    StudyDay,
    StudyPlan,
    StudyTask,
    StudyWeek,
    WeeklyGoal,
)

MODULE_LABEL = {
    "listening": "Listening",
    "reading": "Reading",
    "writing": "Writing",
    "speaking": "Speaking",
    "vocabulary": "Vocabulary",
    "grammar": "Grammar",
}

MODULE_HREF = {
    "listening": "/study-plan/today?skill=listening",
    "reading": "/study-plan/today?skill=reading",
    "writing": "/study-plan/today?skill=writing",
    "speaking": "/study-plan/today?skill=speaking",
    # No grammar/vocab practice bank yet — point tips back to Today.
    "vocabulary": "/study-plan/today",
    "grammar": "/study-plan/today",
}

# skill_tag → preferred display title for drill recommendations
_DRILL_TAG_TITLES: dict[str, str] = {
    "tfng": "True/False/Not Given",
    "ynng": "Yes/No/Not Given",
    "matching_headings": "Matching Headings",
    "matching_information": "Matching Information",
    "matching_features": "Matching Features",
    "matching_sentence_endings": "Matching Sentence Endings",
    "matching": "Matching",
    "sentence_completion": "Sentence Completion",
    "form_completion": "Form Completion",
    "note_completion": "Note Completion",
    "map_labeling": "Map Labelling",
    "map_labelling": "Map Labelling",
    "table_completion": "Table Completion",
    "summary_completion_box": "Summary Completion",
    "flowchart_completion": "Flow-chart Completion",
    "mcq": "Multiple Choice",
}


def _href_for_weak_tag(*, module: str, skill_tag: str) -> str:
    """Deep-link to a matching hub module when catalogue has one; else Today."""
    mod = str(module or "reading").strip().lower()
    tag = str(skill_tag or "").strip().lower().replace(" ", "_").replace("-", "_")
    try:
        from app.practice.catalog import (
            get_hub_skill_tags_by_id,
            get_hub_submit_configs_by_id,
            get_ordered_hub_ids_by_skill,
        )
        from app.practice.module_href import plan_module_href
        from app.practice.weakness import hub_tag_overlap_score, normalize_tag

        ordered = get_ordered_hub_ids_by_skill().get(mod) or []
        tags_by_id = get_hub_skill_tags_by_id()
        submit_by_hub = get_hub_submit_configs_by_id()
        best_id: str | None = None
        best_score = 0
        for hid in ordered:
            score = hub_tag_overlap_score(tags_by_id.get(hid) or [], [normalize_tag(tag)])
            if score > best_score:
                best_score = score
                best_id = hid
        if best_id and best_score > 0:
            cfg = submit_by_hub.get(best_id) or {}
            return plan_module_href(
                skill=mod,
                hub_id=best_id,
                task_type="practice",
                submit_config=cfg if isinstance(cfg, dict) else None,
            )
    except Exception:
        pass
    return f"/study-plan/today?skill={mod}"


def _drill_title_for_tag(skill_tag: str, fallback_label: str) -> str:
    tag = str(skill_tag or "").strip().lower().replace(" ", "_")
    pretty = _DRILL_TAG_TITLES.get(tag)
    if pretty:
        return f"Spend more time on {pretty}"
    # Strip "Reading · tfng (45%)" style labels down to skill name when possible
    label = str(fallback_label or "").strip()
    if "·" in label:
        mid = label.split("·", 1)[1].strip()
        mid = mid.split("(")[0].strip()
        if mid:
            return f"Drill: {mid[:64]}"
    return f"Drill: {label[:64]}" if label else "Drill weak skill"


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _lowest_module(module_summary: dict[str, Any], target: float | None) -> str | None:
    scored: list[tuple[str, float]] = []
    for mod, summary in module_summary.items():
        if not isinstance(summary, dict):
            continue
        latest = summary.get("latest")
        if latest is None:
            continue
        try:
            scored.append((mod, float(latest)))
        except (TypeError, ValueError):
            continue
    if not scored:
        return None
    scored.sort(key=lambda x: x[1])
    lowest = scored[0][0]
    if target is not None:
        try:
            if float(module_summary[lowest]["latest"]) >= float(target):
                # Still return lowest for maintenance
                return lowest
        except (TypeError, ValueError, KeyError):
            pass
    return lowest


def build_recommendations(aggregate: dict[str, Any]) -> list[RecommendationItem]:
    items: list[RecommendationItem] = []
    target = aggregate.get("target_band")
    module_summary = aggregate.get("module_summary") or {}
    weaknesses = aggregate.get("top_weaknesses") or []
    source_counts = aggregate.get("source_counts") or {}
    vocab = aggregate.get("vocab_stats") or {}
    grammar = aggregate.get("grammar_stats") or {}

    total_sources = sum(int(source_counts.get(k) or 0) for k in ("listening", "reading", "writing", "speaking"))

    if total_sources == 0:
        items.append(
            RecommendationItem(
                id="onboard-listening",
                title="Take a listening practice set",
                reason="Your learning profile is empty — a first attempt unlocks personalized focus areas.",
                href="/study-plan/today?skill=listening",
                module="listening",
            )
        )
        items.append(
            RecommendationItem(
                id="onboard-diagnostic",
                title="Complete the free diagnostic",
                reason="A quick skill check seeds your adaptive plan and target-band gap.",
                href="/diagnostic",
                module=None,
            )
        )
        return items[:5]

    lowest = _lowest_module(module_summary, float(target) if target is not None else None)
    if lowest:
        gap = None
        summary = module_summary.get(lowest) or {}
        if isinstance(summary, dict) and target is not None and summary.get("latest") is not None:
            try:
                gap = float(target) - float(summary["latest"])
            except (TypeError, ValueError):
                gap = None
        reason = f"{MODULE_LABEL.get(lowest, lowest)} is your weakest recent module."
        if gap is not None and gap > 0:
            reason = f"{MODULE_LABEL.get(lowest, lowest)} is {gap:.1f} below your target band."
        items.append(
            RecommendationItem(
                id=f"focus-{lowest}",
                title=f"Practice {MODULE_LABEL.get(lowest, lowest)}",
                reason=reason,
                href=MODULE_HREF.get(lowest, "/mocks"),
                module=lowest,
            )
        )

    for weak in weaknesses[:3]:
        if not isinstance(weak, dict):
            continue
        mod = str(weak.get("module") or "reading")
        label = str(weak.get("label") or "Skill gap")
        area = str(weak.get("area") or "")
        skill_tag = ""
        if area.startswith("skill:"):
            skill_tag = area.split(":", 1)[1].strip()
        if not skill_tag and "·" in label:
            # "Reading · tfng (45%)"
            skill_tag = label.split("·", 1)[1].split("(")[0].strip()
        href = (
            _href_for_weak_tag(module=mod, skill_tag=skill_tag)
            if skill_tag
            else MODULE_HREF.get(mod, "/study-plan/today")
        )
        items.append(
            RecommendationItem(
                id=f"weak-{abs(hash(label)) % 10_000}",
                title=_drill_title_for_tag(skill_tag, label),
                reason="Recurring weakness across recent evaluations.",
                href=href,
                module=mod,
            )
        )

    if int(vocab.get("weak_count") or 0) >= 3 or (vocab.get("recurring_weak") or []):
        words = ", ".join((vocab.get("recurring_weak") or [])[:3]) or "high-frequency swaps"
        items.append(
            RecommendationItem(
                id="vocab-growth",
                title="Expand academic vocabulary",
                reason=f"Repeated weak lexical items: {words}.",
                href="/study-plan/today",
                module="vocabulary",
            )
        )

    if int(grammar.get("mistake_count") or 0) >= 3:
        top = (grammar.get("top_issues") or ["accuracy"])[0]
        items.append(
            RecommendationItem(
                id="grammar-trend",
                title="Grammar accuracy drill",
                reason=f"Top recurring issue: {top}.",
                href="/study-plan/today",
                module="grammar",
            )
        )

    # Dedupe by title
    seen: set[str] = set()
    unique: list[RecommendationItem] = []
    for item in items:
        if item.title in seen:
            continue
        seen.add(item.title)
        unique.append(item)
    return unique[:6]


def build_weekly_goals(aggregate: dict[str, Any], recommendations: list[RecommendationItem]) -> list[WeeklyGoal]:
    goals: list[WeeklyGoal] = []
    lowest = _lowest_module(aggregate.get("module_summary") or {}, aggregate.get("target_band"))
    if lowest:
        goals.append(
            WeeklyGoal(
                id="goal-module",
                title=f"Complete 2 {MODULE_LABEL.get(lowest, lowest)} practice sessions",
                module=lowest,
            )
        )
    goals.append(
        WeeklyGoal(
            id="goal-mock",
            title="Finish one timed module mock",
            module=lowest,
        )
    )
    if recommendations:
        rec = recommendations[0]
        goals.append(
            WeeklyGoal(
                id="goal-focus",
                title=rec.title,
                module=rec.module,
            )
        )
    grammar = aggregate.get("grammar_stats") or {}
    if int(grammar.get("mistake_count") or 0) >= 2:
        goals.append(
            WeeklyGoal(
                id="goal-grammar",
                title="Review 10 grammar corrections from recent feedback",
                module="writing",
            )
        )
    vocab = aggregate.get("vocab_stats") or {}
    if vocab.get("recurring_weak"):
        goals.append(
            WeeklyGoal(
                id="goal-vocab",
                title="Learn 8 target vocabulary replacements",
                module="vocabulary",
            )
        )
    if not goals:
        goals.append(
            WeeklyGoal(id="goal-start", title="Complete your first listening practice", module="listening")
        )
    return goals[:5]


def apply_weekly_goal_completion(
    goals: list[WeeklyGoal],
    *,
    study_plan: dict[str, Any] | None = None,
    hub_progress: dict[str, Any] | None = None,
    source_counts: dict[str, Any] | None = None,
    week_start: date | None = None,
) -> list[WeeklyGoal]:
    """Mark weekly goals done from plan/hub/mock signals (read-only for students)."""
    start = week_start or monday_of(date.today())
    end = start + timedelta(days=6)

    # Count done practice tasks this week per module + overall mock completions this week
    module_practice_done: dict[str, int] = {}
    week_task_done = 0
    week_task_total = 0
    if isinstance(study_plan, dict):
        for week in study_plan.get("weeks") or []:
            if not isinstance(week, dict):
                continue
            for day in week.get("days") or []:
                if not isinstance(day, dict):
                    continue
                day_s = str(day.get("date") or "")[:10]
                try:
                    d = date.fromisoformat(day_s)
                except ValueError:
                    continue
                if d < start or d > end:
                    continue
                for task in day.get("tasks") or []:
                    if not isinstance(task, dict):
                        continue
                    week_task_total += 1
                    status = str(task.get("status") or "").lower()
                    if status not in ("done", "completed"):
                        continue
                    week_task_done += 1
                    mod = str(task.get("module") or "").lower()
                    tt = str(task.get("task_type") or "practice").lower()
                    if tt in ("practice", "submit") and mod:
                        module_practice_done[mod] = module_practice_done.get(mod, 0) + 1

    hubs_completed = 0
    if isinstance(hub_progress, dict):
        for skill, prog in hub_progress.items():
            if not isinstance(prog, dict):
                continue
            # SkillHubProgress shape: completed_count or similar
            try:
                hubs_completed += int(
                    prog.get("completed_count")
                    or prog.get("completed")
                    or 0
                )
            except (TypeError, ValueError):
                pass

    sources = source_counts if isinstance(source_counts, dict) else {}
    mock_sessions = sum(
        int(sources.get(k) or 0)
        for k in ("listening", "reading", "writing", "speaking")
    )

    out: list[WeeklyGoal] = []
    for g in goals:
        done = bool(g.done)
        gid = str(g.id or "")
        mod = str(g.module or "").lower() if g.module else ""
        if gid == "goal-module" and mod:
            done = module_practice_done.get(mod, 0) >= 2
        elif gid == "goal-mock":
            done = mock_sessions >= 1 or module_practice_done.get(mod, 0) >= 1
        elif gid == "goal-focus":
            # Any practice this week toward focus module, or overall week progress ≥50%
            if mod and module_practice_done.get(mod, 0) >= 1:
                done = True
            elif week_task_total > 0 and week_task_done / week_task_total >= 0.5:
                done = True
        elif gid == "goal-grammar":
            done = module_practice_done.get("writing", 0) >= 1 or hubs_completed >= 1
        elif gid == "goal-vocab":
            done = week_task_done >= 2
        elif gid == "goal-start":
            done = module_practice_done.get("listening", 0) >= 1 or hubs_completed >= 1
        out.append(g.model_copy(update={"done": done}))
    return out


def _stable_task_id(
    *,
    week_start: date,
    day_offset: int,
    slot: int,
    module: str,
    kind: str,
    title: str,
) -> str:
    """Stable across plan regenerations so PATCH / Continue do not churn."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:36] or "task"
    return f"t-{week_start.isoformat()}-d{day_offset}-s{slot}-{module}-{kind}-{slug}"


def _task(
    *,
    title: str,
    module: str,
    kind: str = "practice",
    duration_min: int = 20,
    subtitle: str = "",
    href: str | None = None,
    status: str = "pending",
    week_start: date | None = None,
    day_offset: int = 0,
    slot: int = 0,
) -> StudyTask:
    if week_start is not None:
        task_id = _stable_task_id(
            week_start=week_start,
            day_offset=day_offset,
            slot=slot,
            module=module,
            kind=kind,
            title=title,
        )
    else:
        # Fallback for unexpected callers — still deterministic from fields.
        task_id = _stable_task_id(
            week_start=date.today(),
            day_offset=day_offset,
            slot=slot,
            module=module,
            kind=kind,
            title=title,
        )
    # Map homework/goal kinds onto practice task_type for Continue CTA eligibility.
    task_type = "practice" if kind in ("practice", "homework", "goal") else "practice"
    return StudyTask(
        id=task_id,
        title=title,
        subtitle=subtitle or f"~{duration_min} min",
        module=module,
        kind=kind,  # type: ignore[arg-type]
        task_type=task_type,  # type: ignore[arg-type]
        duration_min=duration_min,
        href=href or MODULE_HREF.get(module, "/mocks"),
        status=status,  # type: ignore[arg-type]
    )


def build_study_plan(
    aggregate: dict[str, Any],
    recommendations: list[RecommendationItem],
    *,
    week_start: date,
    prior_plan: dict[str, Any] | None = None,
) -> StudyPlan:
    lowest = _lowest_module(aggregate.get("module_summary") or {}, aggregate.get("target_band"))
    focus_mod = lowest or "listening"
    focus_label = MODULE_LABEL.get(focus_mod, focus_mod)
    weekly_focus = f"Strengthen {focus_label}"
    if recommendations:
        weekly_focus = f"{recommendations[0].title} — primary focus this week."

    # Preserve done statuses for same week
    prior_status: dict[str, str] = {}
    if prior_plan and isinstance(prior_plan, dict):
        for week in prior_plan.get("weeks") or []:
            if not isinstance(week, dict):
                continue
            for day in week.get("days") or []:
                if not isinstance(day, dict):
                    continue
                for task in day.get("tasks") or []:
                    if isinstance(task, dict) and task.get("id") and task.get("status"):
                        prior_status[str(task["id"])] = str(task["status"])

    def day_tasks(offset: int, *, plan_week_start: date) -> list[StudyTask]:
        tasks: list[StudyTask] = []
        slot = 0

        def push(
            *,
            title: str,
            module: str,
            kind: str = "practice",
            duration_min: int = 20,
            subtitle: str = "",
            href: str | None = None,
        ) -> None:
            nonlocal slot
            tasks.append(
                _task(
                    title=title,
                    module=module,
                    kind=kind,
                    duration_min=duration_min,
                    subtitle=subtitle,
                    href=href,
                    week_start=plan_week_start,
                    day_offset=offset,
                    slot=slot,
                )
            )
            slot += 1

        if offset == 0:
            push(
                title=f"{focus_label} practice",
                module=focus_mod,
                kind="practice",
                duration_min=25,
                subtitle="Target your lowest module",
            )
            push(
                title="Homework: review feedback notes",
                module=focus_mod if focus_mod in ("writing", "speaking") else "writing",
                kind="homework",
                duration_min=15,
                subtitle="Capture 3 improvements",
            )
        elif offset == 1:
            alt = "reading" if focus_mod != "reading" else "listening"
            push(
                title=f"{MODULE_LABEL[alt]} timed set",
                module=alt,
                duration_min=30,
            )
            # Prefer a real L/R/W/S follow-up — no grammar/vocab content bank yet.
            follow = "writing" if focus_mod not in ("writing",) else "speaking"
            if follow == alt:
                follow = "listening" if alt != "listening" else "reading"
            push(
                title=f"{MODULE_LABEL[follow]} practice set",
                module=follow,
                kind="practice",
                duration_min=20,
                subtitle="Keep momentum on a core skill",
            )
        elif offset == 2:
            push(
                title=f"{focus_label} drill 2",
                module=focus_mod,
                duration_min=25,
            )
            for weak in (aggregate.get("top_weaknesses") or [])[:1]:
                if isinstance(weak, dict):
                    push(
                        title=str(weak.get("label") or "Weakness drill")[:72],
                        module=str(weak.get("module") or focus_mod),
                        kind="homework",
                        duration_min=20,
                    )
        elif offset == 3:
            ws_mod = "writing" if focus_mod != "speaking" else "speaking"
            push(
                title=f"{MODULE_LABEL[ws_mod]} production task",
                module=ws_mod,
                duration_min=40,
            )
        elif offset == 4:
            push(
                title="Mini mock checkpoint",
                module=focus_mod,
                duration_min=35,
                subtitle="Track gap to target",
            )
        else:
            push(
                title="Light review + streak day",
                module=focus_mod,
                duration_min=15,
                kind="goal",
            )
        return tasks

    weeks: list[StudyWeek] = []
    for w in range(2):
        start = week_start + timedelta(days=7 * w)
        days: list[StudyDay] = []
        for d in range(7):
            day_date = start + timedelta(days=d)
            label = day_date.strftime("%a")
            # Absolute day offset from plan week_start keeps IDs unique across weeks.
            abs_offset = 7 * w + (d if w == 0 else min(d, 4))
            tasks = day_tasks(
                d if w == 0 else min(d, 4),
                plan_week_start=week_start,
            )
            # Re-key week-2 tasks with absolute offset so IDs stay unique + stable.
            if w == 1:
                tasks = [
                    _task(
                        title=t.title,
                        module=t.module,
                        kind=t.kind,
                        duration_min=t.duration_min,
                        subtitle=t.subtitle,
                        href=t.href,
                        status=t.status,
                        week_start=week_start,
                        day_offset=abs_offset,
                        slot=i,
                    )
                    for i, t in enumerate(tasks[:2])
                ]
            days.append(
                StudyDay(
                    date=day_date.isoformat(),
                    label=label,
                    tasks=tasks,
                )
            )
        weeks.append(
            StudyWeek(
                id=f"w{w + 1}",
                label=f"Week {w + 1}",
                focus=weekly_focus if w == 0 else f"Continue {focus_label} momentum",
                days=days,
            )
        )

    return StudyPlan(weekly_focus=weekly_focus, weeks=weeks)


def apply_plan_rules(
    aggregate: dict[str, Any],
    *,
    week_start: date | None = None,
    prior_study_plan: dict[str, Any] | None = None,
    prior_week_start: date | None = None,
) -> dict[str, Any]:
    today = date.today()
    start = week_start or monday_of(today)
    recommendations = build_recommendations(aggregate)
    weekly_goals = build_weekly_goals(aggregate, recommendations)

    same_week = prior_week_start == start and prior_study_plan
    # Rebuild plan structure each refresh; task completion merge handled in service by title|date key
    study_plan = build_study_plan(
        aggregate,
        recommendations,
        week_start=start,
        prior_plan=prior_study_plan if same_week else None,
    )

    if same_week and prior_study_plan:
        study_plan = _merge_task_status_by_slot(study_plan, prior_study_plan)

    weekly_goals = apply_weekly_goal_completion(
        weekly_goals,
        study_plan=study_plan.model_dump(),
        source_counts=aggregate.get("source_counts") or {},
        week_start=start,
    )

    return {
        "recommendations": [r.model_dump() for r in recommendations],
        "weekly_goals": [g.model_dump() for g in weekly_goals],
        "study_plan": study_plan.model_dump(),
        "plan_week_start": start.isoformat(),
    }


def _merge_task_status_by_slot(new_plan: StudyPlan, prior: dict[str, Any]) -> StudyPlan:
    """Match tasks by week/day index + title so regeneration keeps completion."""
    prior_by_slot: dict[tuple[int, int, str], str] = {}
    for wi, week in enumerate(prior.get("weeks") or []):
        if not isinstance(week, dict):
            continue
        for di, day in enumerate(week.get("days") or []):
            if not isinstance(day, dict):
                continue
            for task in day.get("tasks") or []:
                if not isinstance(task, dict):
                    continue
                title = str(task.get("title") or "")
                status = str(task.get("status") or "pending")
                if title and status in ("done", "skipped"):
                    prior_by_slot[(wi, di, title)] = status

    weeks: list[StudyWeek] = []
    for wi, week in enumerate(new_plan.weeks):
        days: list[StudyDay] = []
        for di, day in enumerate(week.days):
            tasks: list[StudyTask] = []
            for task in day.tasks:
                status = prior_by_slot.get((wi, di, task.title), task.status)
                tasks.append(task.model_copy(update={"status": status}))  # type: ignore[arg-type]
            days.append(day.model_copy(update={"tasks": tasks}))
        weeks.append(week.model_copy(update={"days": days}))
    return new_plan.model_copy(update={"weeks": weeks})


def _plan_open_href(
    *,
    skill: str,
    hub_id: str,
    task_type: str,
    task_id: str,
    catalog_number: int | None = None,
    part: int | None = None,
    submit_config: dict[str, Any] | None = None,
) -> str:
    """Direct destination for Today links — mock module UI with hub targeting."""
    q_task = f"from=plan&task={task_type}"
    if task_id:
        q_task += f"&taskId={task_id}"
    if task_type == "watch":
        return f"/practice/{skill}/{hub_id}?{q_task}"

    from app.practice.module_href import plan_module_href

    return plan_module_href(
        skill=skill,
        hub_id=hub_id,
        task_type=task_type,
        task_id=task_id,
        catalog_number=int(catalog_number or 1),
        part=part,
        submit_config=submit_config,
    )


def _personalized_task(
    *,
    skill: str,
    task_type: str,
    day_date: date,
    status: str = "pending",
    hub_id: str | None = None,
    slot_index: int = 0,
) -> StudyTask:
    label = SKILL_LABEL.get(skill, skill.title())
    titles = {
        "watch": f"{label} — Watch",
        "practice": f"{label} — Practice",
        "submit": f"{label} — Submit",
    }
    durations = {"watch": 10, "practice": 20, "submit": 15}
    kind = "practice" if task_type in ("watch", "practice") else "homework"
    task_id = f"t-{day_date.isoformat()}-{skill}-{task_type}-s{slot_index}"
    if hub_id:
        href = _plan_open_href(
            skill=skill,
            hub_id=hub_id,
            task_type=task_type,
            task_id=task_id,
        )
    else:
        href = f"/study-plan/today?skill={skill}&unavailable=1"
    return StudyTask(
        id=task_id,
        title=titles[task_type],
        subtitle=f"~{durations[task_type]} min",
        module=skill,
        kind=kind,  # type: ignore[arg-type]
        task_type=task_type,  # type: ignore[arg-type]
        hub_id=hub_id,
        duration_min=durations[task_type],
        href=href,
        status=status,  # type: ignore[arg-type]
    )


def _tasks_for_session_skill(
    skill: str,
    day_date: date,
    prior_status: dict[str, str],
    *,
    hub_id: str | None = None,
    slot_index: int = 0,
) -> list[StudyTask]:
    task_types = ["watch", "practice"]
    if skill in ("writing", "speaking"):
        task_types.append("submit")
    tasks: list[StudyTask] = []
    for task_type in task_types:
        task_id = f"t-{day_date.isoformat()}-{skill}-{task_type}-s{slot_index}"
        # Fall back to legacy id (no slot) so status survives regenerations.
        legacy_id = f"t-{day_date.isoformat()}-{skill}-{task_type}"
        status = prior_status.get(task_id) or prior_status.get(legacy_id, "pending")
        tasks.append(
            _personalized_task(
                skill=skill,
                task_type=task_type,
                day_date=day_date,
                status=status,
                hub_id=hub_id,
                slot_index=slot_index,
            )
        )
    return tasks


def _prior_task_status(prior_plan: dict[str, Any] | None) -> dict[str, str]:
    prior_status: dict[str, str] = {}
    if not prior_plan or not isinstance(prior_plan, dict):
        return prior_status
    for week in prior_plan.get("weeks") or []:
        if not isinstance(week, dict):
            continue
        for day in week.get("days") or []:
            if not isinstance(day, dict):
                continue
            for task in day.get("tasks") or []:
                if isinstance(task, dict) and task.get("id") and task.get("status"):
                    prior_status[str(task["id"])] = str(task["status"])
    return prior_status


def build_personalized_study_plan(
    *,
    bands: dict[str, float | None],
    target: float,
    exam_date: date,
    prep_start: date | None = None,
    plan_tier: str = "full_skill_program",
    diagnostic_attempt_id: str | None = None,
    prior_plan: dict[str, Any] | None = None,
    completed_by_skill: dict[str, int] | None = None,
    weak_tags_by_skill: dict[str, list[str]] | None = None,
    user_id: Any | None = None,
    used_hub_ids: set[str] | None = None,
    used_set_ids: set[str] | None = None,
    hub_to_set: dict[str, str] | None = None,
    assignment_source: str = "plan_generate",
    claim_assignments: bool = False,
) -> StudyPlan:
    """Build an exam-date-bound calendar plan with watch/practice/submit task stubs."""
    start = prep_start or date.today()
    total_days = max((exam_date - start).days + 1, 1)

    floored_gaps = gap_map(bands, target, use_floor=True)
    raw_gaps = gap_map(bands, target, use_floor=False)
    allocation = allocate_days(floored_gaps, total_days)
    focus_queue = build_primary_focus_queue(allocation)
    if len(focus_queue) < total_days:
        focus_queue.extend([SKILL_ORDER[i % len(SKILL_ORDER)] for i in range(total_days - len(focus_queue))])
    focus_queue = focus_queue[:total_days]

    path_kind, session_order = build_session_sequence(bands, target)
    # One Watch+Practice(+Submit) stack per unique skill — Mixed path may
    # repeat skills across H/E slots; expanding every slot bloated the day.
    unique_skills = list(dict.fromkeys(session_order))
    skill_difficulty = classify_skills(bands, target)
    focus_skills = focus_skills_from_gaps(raw_gaps)
    weekly_focus = f"Strengthen {focus_label(focus_skills)}"

    prior_status = _prior_task_status(prior_plan)
    completed_by_skill = completed_by_skill or {}
    weak_tags_by_skill = weak_tags_by_skill or {}

    try:
        from app.practice.catalog import pick_hub_for_slot
    except ImportError:
        pick_hub_for_slot = None  # type: ignore[assignment,misc]

    assigned_hub_ids: list[str] = []
    used_hubs = set(used_hub_ids or [])
    used_sets = set(used_set_ids or [])
    mapping = dict(hub_to_set or {})
    if prior_plan:
        try:
            from app.practice.assignment_ledger import hub_ids_from_study_plan

            for hid in hub_ids_from_study_plan(prior_plan):
                used_hubs.add(hid)
                sid = str(mapping.get(hid) or "").strip()
                if sid:
                    used_sets.add(sid)
        except Exception:
            pass
    if not mapping:
        try:
            from app.practice.catalog import get_hub_set_ids

            mapping = dict(get_hub_set_ids())
        except Exception:
            mapping = {}
    days: list[StudyDay] = []
    for d in range(total_days):
        day_date = start + timedelta(days=d)
        primary_skill = focus_queue[d]
        tasks: list[StudyTask] = []
        for slot_index, skill in enumerate(unique_skills):
            hub_id = None
            if pick_hub_for_slot is not None:
                try:
                    hub_id = pick_hub_for_slot(
                        skill=skill,
                        day_index=d,
                        slot_index=slot_index,
                        completed_count=int(completed_by_skill.get(skill, 0)),
                        used_hub_ids=used_hubs,
                        used_set_ids=used_sets,
                        hub_to_set=mapping,
                        weak_tags=weak_tags_by_skill.get(skill) or None,
                        user_id=user_id,
                        source=assignment_source,
                        assigned_on=day_date,
                        claim=bool(claim_assignments and user_id),
                    )
                except Exception:
                    hub_id = None
                if hub_id:
                    assigned_hub_ids.append(hub_id)
                    used_hubs.add(hub_id)
                    sid = str(mapping.get(hub_id) or "").strip()
                    if sid:
                        used_sets.add(sid)
            tasks.extend(
                _tasks_for_session_skill(
                    skill,
                    day_date,
                    prior_status,
                    hub_id=hub_id,
                    slot_index=slot_index,
                )
            )
        days.append(
            StudyDay(
                date=day_date.isoformat(),
                label=day_date.strftime("%a"),
                tasks=tasks,
            )
        )

    weeks: list[StudyWeek] = []
    for w in range((total_days + 6) // 7):
        chunk = days[w * 7 : (w + 1) * 7]
        if not chunk:
            continue
        week_start = date.fromisoformat(chunk[0].date)
        weeks.append(
            StudyWeek(
                id=f"w{w + 1}",
                label=f"Week {w + 1}",
                focus=weekly_focus if w == 0 else f"Continue — {focus_label(focus_skills)}",
                days=chunk,
            )
        )

    return StudyPlan(
        weekly_focus=weekly_focus,
        weeks=weeks,
        prep_start=start,
        exam_date=exam_date,
        total_days=total_days,
        plan_tier=plan_tier,
        skill_difficulty=skill_difficulty,
        session_path_kind=path_kind,
        diagnostic_attempt_id=diagnostic_attempt_id,
        assigned_hub_ids=list(dict.fromkeys(assigned_hub_ids)),
    )
