"""Question Bank assignment invariant validation.

Reports violations. Never repairs data. Safe for tests and staging diagnostics.
user_id is an opaque UUID — do not attach emails or names.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from app.practice.assignment_ledger import (
    hub_ids_from_study_plan,
    is_question_bank_hub,
)
from app.practice.repository import SKILLS


@dataclass
class InvariantIssue:
    kind: str
    user_id: str
    practice_set_id: str | None = None
    hub_ids: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _hubs_by_skill_from_plan(
    study_plan: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(study_plan, dict):
        return out
    for week in study_plan.get("weeks") or []:
        if not isinstance(week, dict):
            continue
        for day in week.get("days") or []:
            if not isinstance(day, dict):
                continue
            by_skill: dict[str, dict[str, str | None]] = {}
            for task in day.get("tasks") or []:
                if not isinstance(task, dict):
                    continue
                skill = str(task.get("module") or "").strip().lower()
                if skill not in SKILLS:
                    continue
                tt = str(task.get("task_type") or "practice")
                hid = str(task.get("hub_id") or "").strip() or None
                by_skill.setdefault(skill, {})[tt] = hid
            out.append({"date": str(day.get("date") or ""), "hubs": by_skill})
    return out


def validate_user_practice_invariants(
    *,
    user_id: str,
    ledger_rows: list[dict[str, Any]] | None = None,
    study_plan: dict[str, Any] | None = None,
    progress_rows: list[dict[str, Any]] | None = None,
    hub_to_set: dict[str, str] | None = None,
    hub_meta: dict[str, dict[str, Any]] | None = None,
    today: date | None = None,
) -> list[InvariantIssue]:
    """Detect duplicate set/hub ids and ledger/plan mismatches for one user."""
    del today
    uid = str(user_id)
    mapping = hub_to_set or {}
    meta = hub_meta or {}
    issues: list[InvariantIssue] = []

    ledger_hubs: list[str] = []
    ledger_sets: list[str] = []
    ledger_set_hubs: dict[str, list[str]] = defaultdict(list)
    for row in ledger_rows or []:
        hid = str(row.get("hub_id") or "").strip()
        sid = str(row.get("practice_set_id") or mapping.get(hid) or "").strip()
        if hid:
            ledger_hubs.append(hid)
            if sid:
                ledger_sets.append(sid)
                ledger_set_hubs[sid].append(hid)

    plan_hubs = hub_ids_from_study_plan(study_plan)
    plan_hub_occurrences: list[str] = []
    for day in _hubs_by_skill_from_plan(study_plan):
        day_seen: set[str] = set()
        for slots in (day.get("hubs") or {}).values():
            for hid in slots.values():
                if hid and hid not in day_seen:
                    day_seen.add(hid)
                    plan_hub_occurrences.append(hid)
    plan_sets = [mapping[h] for h in plan_hub_occurrences if mapping.get(h)]

    progress_hubs: list[str] = []
    for row in progress_rows or []:
        if isinstance(row, dict):
            hid = str(row.get("hub_id") or "").strip()
        else:
            hid = str(row or "").strip()
        if hid:
            progress_hubs.append(hid)
    progress_sets = [mapping[h] for h in progress_hubs if mapping.get(h)]

    def _dup(kind: str, values: list[str], source: str, *, as_set: bool) -> None:
        seen: dict[str, int] = defaultdict(int)
        for v in values:
            if v:
                seen[v] += 1
        for val, n in seen.items():
            if n > 1:
                issues.append(
                    InvariantIssue(
                        kind=kind,
                        user_id=uid,
                        practice_set_id=val if as_set else mapping.get(val),
                        hub_ids=ledger_set_hubs.get(val, [val] if not as_set else []),
                        sources=[source],
                        detail=f"{kind} x{n} in {source}",
                    )
                )

    _dup("duplicate_practice_set_id", ledger_sets, "ledger", as_set=True)
    _dup("duplicate_practice_set_id", plan_sets, "study_plan", as_set=True)
    _dup("duplicate_practice_set_id", progress_sets, "progress", as_set=True)
    _dup("duplicate_hub_id", ledger_hubs, "ledger", as_set=False)
    _dup("duplicate_hub_id", plan_hub_occurrences, "study_plan", as_set=False)
    _dup("duplicate_hub_id", progress_hubs, "progress", as_set=False)

    set_to_hubs: dict[str, set[str]] = defaultdict(set)
    for hid in plan_hubs + ledger_hubs + progress_hubs:
        sid = mapping.get(hid) or ""
        if sid:
            set_to_hubs[sid].add(hid)
    for row in ledger_rows or []:
        sid = str(row.get("practice_set_id") or "").strip()
        hid = str(row.get("hub_id") or "").strip()
        if sid and hid:
            set_to_hubs[sid].add(hid)
    for sid, hubs in set_to_hubs.items():
        if len(hubs) > 1:
            issues.append(
                InvariantIssue(
                    kind="duplicate_practice_set_id",
                    user_id=uid,
                    practice_set_id=sid,
                    hub_ids=sorted(hubs),
                    sources=["ledger", "study_plan", "progress"],
                    detail="same practice_set_id mapped to multiple hub_ids",
                )
            )

    ledger_hub_set = set(ledger_hubs)
    plan_hub_set = set(plan_hubs)
    for hid in sorted(ledger_hub_set - plan_hub_set):
        issues.append(
            InvariantIssue(
                kind="ledger_missing_from_plan",
                user_id=uid,
                practice_set_id=mapping.get(hid),
                hub_ids=[hid],
                sources=["ledger"],
                detail="ledger hub is not on study_plan",
            )
        )
    qb_plan_hubs = []
    for hid in plan_hubs:
        meta_row = meta.get(hid)
        if meta_row is None or is_question_bank_hub(meta_row):
            qb_plan_hubs.append(hid)
    for hid in sorted(set(qb_plan_hubs) - ledger_hub_set):
        issues.append(
            InvariantIssue(
                kind="plan_missing_from_ledger",
                user_id=uid,
                practice_set_id=mapping.get(hid),
                hub_ids=[hid],
                sources=["study_plan"],
                detail="Question Bank plan hub has no ledger row",
            )
        )

    for hid in plan_hubs + ledger_hubs:
        row = meta.get(hid)
        if not row:
            continue
        if not is_question_bank_hub(row):
            issues.append(
                InvariantIssue(
                    kind="non_bank_hub",
                    user_id=uid,
                    practice_set_id=str(row.get("set_id") or mapping.get(hid) or "") or None,
                    hub_ids=[hid],
                    sources=["hub_meta"],
                    detail="assignment points at a non-Question-Bank hub",
                )
            )
        status = str(row.get("status") or row.get("set_status") or "").strip().lower()
        if status and status != "published":
            issues.append(
                InvariantIssue(
                    kind="unpublished_set",
                    user_id=uid,
                    practice_set_id=str(row.get("set_id") or mapping.get(hid) or "") or None,
                    hub_ids=[hid],
                    sources=["hub_meta"],
                    detail=f"assignment points at set status={status}",
                )
            )

    issues.extend(same_day_stack_issues(user_id=uid, study_plan=study_plan))
    return issues


def same_day_stack_issues(
    *,
    user_id: str,
    study_plan: dict[str, Any] | None,
) -> list[InvariantIssue]:
    issues: list[InvariantIssue] = []
    for day in _hubs_by_skill_from_plan(study_plan):
        for skill, slots in (day.get("hubs") or {}).items():
            hubs = list(slots.values())
            nonempty = [h for h in hubs if h]
            if nonempty and (len(set(nonempty)) > 1 or any(h is None for h in hubs)):
                issues.append(
                    InvariantIssue(
                        kind="same_day_stack_mismatch",
                        user_id=str(user_id),
                        hub_ids=sorted(set(hubs)),
                        sources=["study_plan"],
                        detail=f"{skill} {day.get('date')} watch/practice/submit differ",
                    )
                )
    return issues


def cross_skill_mutation_issues(
    *,
    user_id: str,
    before: dict[str, Any],
    after: dict[str, Any],
    target_skill: str,
) -> list[InvariantIssue]:
    """True when a fill for target_skill changed another skill's hubs."""
    issues: list[InvariantIssue] = []
    skill_n = str(target_skill or "").strip().lower()
    before_days = _hubs_by_skill_from_plan(before)
    after_days = _hubs_by_skill_from_plan(after)
    for b, a in zip(before_days, after_days):
        bh, ah = b.get("hubs") or {}, a.get("hubs") or {}
        for skill in SKILLS:
            if skill == skill_n:
                continue
            if bh.get(skill) != ah.get(skill):
                issues.append(
                    InvariantIssue(
                        kind="cross_skill_mutation",
                        user_id=str(user_id),
                        sources=["study_plan"],
                        detail=f"{skill} changed during {skill_n} fill on {b.get('date')}",
                    )
                )
    return issues
