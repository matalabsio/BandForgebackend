"""Phase 5: invariant validator reports, never repairs."""

from __future__ import annotations

from datetime import date, timedelta

from app.practice.invariants import (
    cross_skill_mutation_issues,
    same_day_stack_issues,
    validate_user_practice_invariants,
)

USER = "00000000-0000-0000-0000-0000000000aa"
TODAY = date(2026, 8, 18)


def _day(d: date, listening: str | None, reading: str | None = "r1") -> dict:
    tasks = [
        {"id": "lw", "module": "listening", "task_type": "watch", "hub_id": listening},
        {"id": "lp", "module": "listening", "task_type": "practice", "hub_id": listening},
        {"id": "ls", "module": "listening", "task_type": "submit", "hub_id": listening},
    ]
    if reading is not None:
        tasks.append(
            {"id": "rp", "module": "reading", "task_type": "practice", "hub_id": reading}
        )
    return {"date": d.isoformat(), "tasks": tasks}


def _plan(hubs: list[str | None]) -> dict:
    days = [_day(TODAY + timedelta(days=i), h) for i, h in enumerate(hubs)]
    return {
        "prep_start": TODAY.isoformat(),
        "assigned_hub_ids": [h for h in hubs if h],
        "weeks": [{"id": "w1", "days": days}],
    }


def test_detects_duplicate_set_across_hubs():
    issues = validate_user_practice_invariants(
        user_id=USER,
        ledger_rows=[
            {"hub_id": "h1", "practice_set_id": "set-a"},
            {"hub_id": "h2", "practice_set_id": "set-a"},
        ],
        study_plan=_plan(["h1"]),
        hub_to_set={"h1": "set-a", "h2": "set-a"},
    )
    kinds = {i.kind for i in issues}
    assert "duplicate_practice_set_id" in kinds
    hit = [i for i in issues if i.kind == "duplicate_practice_set_id"][0]
    assert hit.user_id == USER
    assert hit.practice_set_id == "set-a"
    assert set(hit.hub_ids) >= {"h1", "h2"}


def test_detects_duplicate_hub_in_plan():
    plan = _plan(["h1", "h1"])
    issues = validate_user_practice_invariants(
        user_id=USER,
        ledger_rows=[{"hub_id": "h1", "practice_set_id": "s1"}],
        study_plan=plan,
        hub_to_set={"h1": "s1"},
    )
    assert any(i.kind == "duplicate_hub_id" for i in issues)


def test_ledger_plan_mismatch_and_missing_ledger():
    issues = validate_user_practice_invariants(
        user_id=USER,
        ledger_rows=[{"hub_id": "orphan", "practice_set_id": "s-orphan"}],
        study_plan=_plan(["h1"]),
        hub_to_set={"h1": "s1", "orphan": "s-orphan"},
        hub_meta={
            "h1": {
                "id": "h1",
                "set_id": "s1",
                "submit_config": {"type": "bank"},
                "practice_sets": {
                    "id": "s1",
                    "status": "published",
                    "practice_banks": {"skill": "listening", "bank_number": 5},
                },
            }
        },
    )
    kinds = {i.kind for i in issues}
    assert "ledger_missing_from_plan" in kinds
    assert "plan_missing_from_ledger" in kinds


def test_non_bank_and_unpublished_flags():
    issues = validate_user_practice_invariants(
        user_id=USER,
        ledger_rows=[{"hub_id": "mock", "practice_set_id": "legacy"}],
        study_plan=_plan(["mock"]),
        hub_to_set={"mock": "legacy"},
        hub_meta={
            "mock": {
                "id": "mock",
                "set_id": "legacy",
                "submit_config": {"type": "module"},
                "status": "draft",
                "practice_sets": {
                    "id": "legacy",
                    "status": "draft",
                    "practice_banks": {"skill": "listening", "bank_number": 1},
                },
            }
        },
    )
    kinds = {i.kind for i in issues}
    assert "non_bank_hub" in kinds
    assert "unpublished_set" in kinds


def test_same_day_stack_must_share_hub():
    plan = {
        "weeks": [
            {
                "days": [
                    {
                        "date": TODAY.isoformat(),
                        "tasks": [
                            {
                                "module": "listening",
                                "task_type": "watch",
                                "hub_id": "h1",
                            },
                            {
                                "module": "listening",
                                "task_type": "practice",
                                "hub_id": "h2",
                            },
                        ],
                    }
                ]
            }
        ]
    }
    issues = same_day_stack_issues(user_id=USER, study_plan=plan)
    assert issues and issues[0].kind == "same_day_stack_mismatch"


def test_validator_does_not_repair():
    plan = _plan(["h1", "h1"])
    before = str(plan)
    validate_user_practice_invariants(
        user_id=USER,
        ledger_rows=[{"hub_id": "h1", "practice_set_id": "s1"}] * 2,
        study_plan=plan,
        hub_to_set={"h1": "s1"},
    )
    assert str(plan) == before


def test_cross_skill_isolation_helper():
    before = _plan(["s1", None])
    after = _plan(["s1", "s5"])
    # reading hubs stay r1
    assert cross_skill_mutation_issues(
        user_id=USER, before=before, after=after, target_skill="listening"
    ) == []
    after["weeks"][0]["days"][0]["tasks"][-1]["hub_id"] = "r-changed"
    issues = cross_skill_mutation_issues(
        user_id=USER, before=before, after=after, target_skill="listening"
    )
    assert issues and issues[0].kind == "cross_skill_mutation"
