"""Phase 3: unique unused picker + sticky rewrite."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID

from app.learning.rules import build_personalized_study_plan
from app.practice.assignment import pick_hub_for_slot, pick_unused_hub, rewrite_plan_hubs
from app.practice.assignment_ledger import is_question_bank_hub, try_claim_practice_assignment

USER_A = UUID("00000000-0000-0000-0000-0000000000aa")


def _mapping(hubs: list[str]) -> dict[str, str]:
    return {h: f"set-{h}" for h in hubs}


def _listening_days(*, start: date, n: int, hubs: list[str | None]) -> dict:
    days = []
    for i in range(n):
        hid = hubs[i] if i < len(hubs) else None
        days.append(
            {
                "date": (start + timedelta(days=i)).isoformat(),
                "label": "D",
                "tasks": [
                    {
                        "id": f"w-{i}",
                        "module": "listening",
                        "task_type": "watch",
                        "hub_id": hid,
                        "status": "pending",
                    },
                    {
                        "id": f"p-{i}",
                        "module": "listening",
                        "task_type": "practice",
                        "hub_id": hid,
                        "status": "pending",
                    },
                ],
            }
        )
    return {
        "prep_start": start.isoformat(),
        "weeks": [{"id": "w1", "label": "W1", "focus": "x", "days": days}],
    }


def _listening_hubs_from_plan(plan) -> list[str | None]:
    out: list[str | None] = []
    weeks = plan.weeks if hasattr(plan, "weeks") else plan.get("weeks")
    for week in weeks:
        days = week.days if hasattr(week, "days") else week.get("days")
        for day in days:
            tasks = day.tasks if hasattr(day, "tasks") else day.get("tasks")
            watches = [
                t
                for t in tasks
                if (t.module if hasattr(t, "module") else t.get("module")) == "listening"
                and (t.task_type if hasattr(t, "task_type") else t.get("task_type"))
                == "watch"
            ]
            if not watches:
                continue
            t0 = watches[0]
            hid = t0.hub_id if hasattr(t0, "hub_id") else t0.get("hub_id")
            out.append(hid if hid else None)
    return out


def test_one_set_multiple_days_no_repeat():
    hubs = ["S1"]
    used_h: set[str] = set()
    used_s: set[str] = set()
    picks = [
        pick_hub_for_slot(
            skill="listening",
            hub_ids=hubs,
            hub_to_set=_mapping(hubs),
            used_hub_ids=used_h,
            used_set_ids=used_s,
        )
        for _ in range(4)
    ]
    assert picks == ["S1", None, None, None]


def test_four_sets_ten_days_unique_then_unavailable():
    ordered = {
        "listening": ["S1", "S2", "S3", "S4"],
        "reading": [f"R{i}" for i in range(20)],
        "writing": [f"W{i}" for i in range(20)],
        "speaking": [f"K{i}" for i in range(20)],
    }
    mapping = {h: f"set-{h}" for ids in ordered.values() for h in ids}
    today = date(2026, 8, 1)
    with (
        patch(
            "app.practice.catalog.get_ordered_question_bank_ids_by_skill",
            return_value=ordered,
        ),
        patch("app.practice.catalog.get_hub_set_ids", return_value=mapping),
        patch("app.practice.catalog.get_hub_skill_tags_by_id", return_value={}),
    ):
        plan = build_personalized_study_plan(
            bands={"listening": 4.0, "reading": 4.0, "writing": 2.0, "speaking": 2.0},
            target=7.0,
            exam_date=today + timedelta(days=9),
            prep_start=today,
            hub_to_set=mapping,
        )
    listening = _listening_hubs_from_plan(plan)
    assert len(listening) == 10
    assigned = [h for h in listening if h]
    assert assigned == ["S1", "S2", "S3", "S4"]
    assert listening[4:] == [None] * 6
    assert len(set(assigned)) == 4


def test_new_catalog_item_fills_empty_without_reshuffle():
    start = date(2026, 8, 1)
    plan = _listening_days(start=start, n=5, hubs=["S1", "S2", "S3", "S4", None])
    pool = ["S1", "S2", "S3", "S4", "S5"]
    out = rewrite_plan_hubs(
        plan,
        ordered_ids={"listening": pool, "reading": [], "writing": [], "speaking": []},
        hub_to_set=_mapping(pool),
        today=start,
        claim=False,
    )
    hubs = _listening_hubs_from_plan(out)
    assert hubs[:4] == ["S1", "S2", "S3", "S4"]
    assert hubs[4] == "S5"


def test_ledger_used_skips_s5():
    hubs = ["S1", "S5", "S6"]
    assert (
        pick_hub_for_slot(
            skill="listening",
            hub_ids=hubs,
            hub_to_set=_mapping(hubs),
            used_hub_ids={"S5"},
            used_set_ids={"set-S5"},
        )
        == "S1"
    )


def test_plan_hub_without_ledger_is_used():
    start = date(2026, 8, 1)
    plan = _listening_days(start=start, n=2, hubs=["S5", None])
    pool = ["S5", "S6"]
    out = rewrite_plan_hubs(
        plan,
        ordered_ids={"listening": pool, "reading": [], "writing": [], "speaking": []},
        hub_to_set=_mapping(pool),
        today=start,
        claim=False,
        used_hub_ids=set(),
        used_set_ids=set(),
    )
    hubs = _listening_hubs_from_plan(out)
    assert hubs[0] == "S5"
    assert hubs[1] == "S6"


def test_completed_hub_is_not_reselected():
    hubs = ["S5", "S6"]
    assert (
        pick_hub_for_slot(
            skill="listening",
            hub_ids=hubs,
            hub_to_set=_mapping(hubs),
            used_hub_ids={"S5"},
            used_set_ids={"set-S5"},
        )
        == "S6"
    )


def test_same_set_two_hubs_skipped():
    hubs = ["h-a", "h-b"]
    mapping = {"h-a": "set-1", "h-b": "set-1"}
    used_h: set[str] = set()
    used_s: set[str] = set()
    first = pick_hub_for_slot(
        skill="listening",
        hub_ids=hubs,
        hub_to_set=mapping,
        used_hub_ids=used_h,
        used_set_ids=used_s,
    )
    second = pick_hub_for_slot(
        skill="listening",
        hub_ids=hubs,
        hub_to_set=mapping,
        used_hub_ids=used_h,
        used_set_ids=used_s,
    )
    assert first == "h-a"
    assert second is None


def test_two_users_may_receive_same_set():
    hubs = ["S5"]
    a = pick_unused_hub(
        hub_ids=hubs, used_hub_ids=set(), used_set_ids=set(), hub_to_set=_mapping(hubs)
    )
    b = pick_unused_hub(
        hub_ids=hubs, used_hub_ids=set(), used_set_ids=set(), hub_to_set=_mapping(hubs)
    )
    assert a == b == "S5"


def test_same_day_watch_practice_submit_share_hub():
    start = date(2026, 8, 1)
    plan = {
        "prep_start": start.isoformat(),
        "weeks": [
            {
                "id": "w1",
                "label": "W1",
                "focus": "x",
                "days": [
                    {
                        "date": start.isoformat(),
                        "tasks": [
                            {"id": "w", "module": "speaking", "task_type": "watch", "hub_id": None},
                            {"id": "p", "module": "speaking", "task_type": "practice", "hub_id": None},
                            {"id": "s", "module": "speaking", "task_type": "submit", "hub_id": None},
                        ],
                    }
                ],
            }
        ],
    }
    out = rewrite_plan_hubs(
        plan,
        ordered_ids={
            "listening": [],
            "reading": [],
            "writing": [],
            "speaking": ["SP1", "SP2"],
        },
        hub_to_set={"SP1": "set-sp1", "SP2": "set-sp2"},
        today=start,
        claim=False,
    )
    tasks = out["weeks"][0]["days"][0]["tasks"]
    assert {t["hub_id"] for t in tasks} == {"SP1"}


def test_past_assignment_unchanged():
    start = date(2026, 8, 1)
    today = date(2026, 8, 3)
    plan = _listening_days(start=start, n=2, hubs=["S1", "S2"])
    out = rewrite_plan_hubs(
        plan,
        ordered_ids={"listening": ["S9"], "reading": [], "writing": [], "speaking": []},
        hub_to_set=_mapping(["S1", "S2", "S9"]),
        today=today,
        claim=False,
    )
    assert _listening_hubs_from_plan(out) == ["S1", "S2"]


def test_started_and_completed_today_unchanged():
    today = date(2026, 8, 18)
    plan = _listening_days(start=today, n=1, hubs=["S5"])
    for status in ("in_progress", "completed"):
        out = rewrite_plan_hubs(
            plan,
            ordered_ids={"listening": ["S9"], "reading": [], "writing": [], "speaking": []},
            hub_to_set=_mapping(["S5", "S9"]),
            progress_map={"S5": {"status": status}},
            today=today,
            claim=False,
        )
        assert _listening_hubs_from_plan(out) == ["S5"]


def test_future_assigned_day_unchanged():
    today = date(2026, 8, 1)
    plan = _listening_days(start=today, n=2, hubs=["S1", "S2"])
    out = rewrite_plan_hubs(
        plan,
        ordered_ids={"listening": ["S9"], "reading": [], "writing": [], "speaking": []},
        hub_to_set=_mapping(["S1", "S2", "S9"]),
        today=today,
        claim=False,
    )
    assert _listening_hubs_from_plan(out)[1] == "S2"


def test_future_empty_filled_from_unused_catalog():
    today = date(2026, 8, 1)
    plan = _listening_days(start=today, n=2, hubs=["S1", None])
    out = rewrite_plan_hubs(
        plan,
        ordered_ids={"listening": ["S1", "S5"], "reading": [], "writing": [], "speaking": []},
        hub_to_set=_mapping(["S1", "S5"]),
        today=today,
        claim=False,
    )
    assert _listening_hubs_from_plan(out) == ["S1", "S5"]


def test_new_catalog_item_does_not_reshuffle_assigned():
    today = date(2026, 8, 1)
    plan = _listening_days(start=today, n=2, hubs=["S1", "S2"])
    out = rewrite_plan_hubs(
        plan,
        ordered_ids={"listening": ["S5", "S1", "S2"], "reading": [], "writing": [], "speaking": []},
        hub_to_set=_mapping(["S1", "S2", "S5"]),
        today=today,
        claim=False,
    )
    assert _listening_hubs_from_plan(out) == ["S1", "S2"]


def test_claim_already_owned_reuses_same_hub():
    used_h: set[str] = set()
    used_s: set[str] = set()
    with patch(
        "app.practice.assignment._claim_candidate",
        return_value="already",
    ):
        first = pick_hub_for_slot(
            skill="listening",
            hub_ids=["S5", "S6"],
            hub_to_set=_mapping(["S5", "S6"]),
            used_hub_ids=used_h,
            used_set_ids=used_s,
            user_id=USER_A,
            claim=True,
            source="plan_generate",
        )
    assert first == "S5"
    assert "S6" not in used_h


def test_concurrent_conflict_skips_to_next_unused():
    used_h: set[str] = set()
    used_s: set[str] = set()
    with patch(
        "app.practice.assignment._claim_candidate",
        side_effect=["conflict", "claimed"],
    ):
        hub = pick_hub_for_slot(
            skill="listening",
            hub_ids=["S5", "S6"],
            hub_to_set=_mapping(["S5", "S6"]),
            used_hub_ids=used_h,
            used_set_ids=used_s,
            user_id=USER_A,
            claim=True,
            source="serve_fill",
        )
    assert hub == "S6"
    assert "S5" in used_h
    assert "S6" in used_h


def test_mock_and_module_hubs_are_not_question_bank():
    mockish = {
        "id": "phase0-hub",
        "set_id": "legacy",
        "submit_config": {"type": "module"},
        "practice_sets": {
            "id": "legacy",
            "practice_banks": {"skill": "listening", "bank_number": 1},
        },
    }
    bank = {
        "id": "qb-hub",
        "set_id": "qb-set",
        "submit_config": {"type": "bank"},
        "practice_sets": {
            "id": "qb-set",
            "practice_banks": {"skill": "listening", "bank_number": 5},
        },
    }
    assert is_question_bank_hub(mockish) is False
    assert is_question_bank_hub(bank) is True


def test_try_claim_returns_conflict_on_unique_violation():
    from postgrest.exceptions import APIError

    insert_chain = MagicMock()
    insert_chain.insert.return_value = insert_chain
    select_chain = MagicMock()
    select_chain.select.return_value = select_chain
    select_chain.eq.return_value = select_chain
    sb = MagicMock()
    calls = {"n": 0}

    def table(_name: str):
        calls["n"] += 1
        return insert_chain if calls["n"] == 1 else select_chain

    sb.table.side_effect = table
    err = APIError({"message": "duplicate key", "code": "23505"})
    with (
        patch("app.practice.assignment_ledger.get_supabase", return_value=sb),
        patch(
            "app.practice.assignment_ledger._exec",
            side_effect=[
                err,
                MagicMock(data=[{"hub_id": "other", "practice_set_id": "set-S5"}]),
            ],
        ),
    ):
        status = try_claim_practice_assignment(
            user_id=USER_A,
            hub_id="S5",
            practice_set_id="set-S5",
            skill="listening",
            source="plan_generate",
        )
    assert status == "conflict"


def test_no_modulo_in_assignment_module():
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "app" / "practice" / "assignment.py"
    text = src.read_text()
    assert "% n" not in text
    assert "% pool" not in text
    assert "soft-repeat" not in text
