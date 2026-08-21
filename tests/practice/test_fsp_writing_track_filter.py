"""Phase 2: FSP Writing filtered by users.exam_module (Writing only)."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.practice.assignment import pick_hub_for_slot, rewrite_plan_hubs
from app.practice.catalog_jobs import offer_published_set
from app.practice.writing_track import (
    filter_writing_hub_ids,
    fsp_writing_track_ready,
    writing_set_compatible_with_user,
)

USER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
HUB_ACAD = "hub-acad-t1"
HUB_GT = "hub-gt-t1"
HUB_BOTH = "hub-both-t2"
HUB_NULL = "hub-null"
HUB_L = "hub-listen-1"
HUB_R = "hub-read-1"
HUB_S = "hub-speak-1"

EXAM_MAP = {
    HUB_ACAD: "academic",
    HUB_GT: "general_training",
    HUB_BOTH: "both",
    HUB_NULL: None,
    HUB_L: None,
    HUB_R: None,
    HUB_S: None,
}

SET_MAP = {
    HUB_ACAD: "set-acad",
    HUB_GT: "set-gt",
    HUB_BOTH: "set-both",
    HUB_NULL: "set-null",
    HUB_L: "set-l",
    HUB_R: "set-r",
    HUB_S: "set-s",
}


# ── Compatibility helpers ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "user,set_mod,ok",
    [
        ("academic", "academic", True),
        ("academic", "both", True),
        ("academic", "general_training", False),
        ("academic", None, False),
        ("general_training", "general_training", True),
        ("general_training", "both", True),
        ("general_training", "academic", False),
        ("general_training", None, False),
        (None, "academic", False),
        (None, "both", False),
        (None, "general_training", False),
    ],
)
def test_writing_set_compatible_matrix(user, set_mod, ok):
    assert (
        writing_set_compatible_with_user(
            set_exam_module=set_mod, user_exam_module=user
        )
        is ok
    )


def test_null_user_track_not_ready():
    assert fsp_writing_track_ready(None) is False
    assert fsp_writing_track_ready("academic") is True
    assert fsp_writing_track_ready("general_training") is True


def test_filter_writing_hub_ids_academic():
    ids = filter_writing_hub_ids(
        [HUB_ACAD, HUB_GT, HUB_BOTH, HUB_NULL],
        hub_exam_module_by_id=EXAM_MAP,
        user_exam_module="academic",
    )
    assert ids == [HUB_ACAD, HUB_BOTH]


def test_filter_writing_hub_ids_gt():
    ids = filter_writing_hub_ids(
        [HUB_ACAD, HUB_GT, HUB_BOTH, HUB_NULL],
        hub_exam_module_by_id=EXAM_MAP,
        user_exam_module="general_training",
    )
    assert ids == [HUB_GT, HUB_BOTH]


def test_filter_writing_hub_ids_null_user_empty():
    ids = filter_writing_hub_ids(
        [HUB_ACAD, HUB_GT, HUB_BOTH],
        hub_exam_module_by_id=EXAM_MAP,
        user_exam_module=None,
    )
    assert ids == []


# ── pick_hub_for_slot ───────────────────────────────────────────────────────


def test_pick_academic_receives_academic_and_both_not_gt():
    used: set[str] = set()
    used_sets: set[str] = set()
    pool = [HUB_GT, HUB_ACAD, HUB_BOTH]
    first = pick_hub_for_slot(
        skill="writing",
        hub_ids=pool,
        used_hub_ids=used,
        used_set_ids=used_sets,
        hub_to_set=SET_MAP,
        user_exam_module="academic",
        hub_exam_module_by_id=EXAM_MAP,
        claim=False,
    )
    assert first == HUB_ACAD
    second = pick_hub_for_slot(
        skill="writing",
        hub_ids=pool,
        used_hub_ids=used,
        used_set_ids=used_sets,
        hub_to_set=SET_MAP,
        user_exam_module="academic",
        hub_exam_module_by_id=EXAM_MAP,
        claim=False,
    )
    assert second == HUB_BOTH
    third = pick_hub_for_slot(
        skill="writing",
        hub_ids=pool,
        used_hub_ids=used,
        used_set_ids=used_sets,
        hub_to_set=SET_MAP,
        user_exam_module="academic",
        hub_exam_module_by_id=EXAM_MAP,
        claim=False,
    )
    assert third is None


def test_pick_gt_receives_gt_and_both_not_academic():
    used: set[str] = set()
    used_sets: set[str] = set()
    pool = [HUB_ACAD, HUB_GT, HUB_BOTH]
    first = pick_hub_for_slot(
        skill="writing",
        hub_ids=pool,
        used_hub_ids=used,
        used_set_ids=used_sets,
        hub_to_set=SET_MAP,
        user_exam_module="general_training",
        hub_exam_module_by_id=EXAM_MAP,
        claim=False,
    )
    assert first == HUB_GT
    second = pick_hub_for_slot(
        skill="writing",
        hub_ids=pool,
        used_hub_ids=used,
        used_set_ids=used_sets,
        hub_to_set=SET_MAP,
        user_exam_module="general_training",
        hub_exam_module_by_id=EXAM_MAP,
        claim=False,
    )
    assert second == HUB_BOTH


def test_pick_null_exam_module_assigns_no_writing():
    hub = pick_hub_for_slot(
        skill="writing",
        hub_ids=[HUB_ACAD, HUB_GT, HUB_BOTH],
        hub_to_set=SET_MAP,
        user_exam_module=None,
        hub_exam_module_by_id=EXAM_MAP,
        claim=False,
    )
    assert hub is None


def test_listening_pool_unchanged_for_academic_user():
    hub = pick_hub_for_slot(
        skill="listening",
        hub_ids=[HUB_L],
        hub_to_set=SET_MAP,
        user_exam_module="academic",
        hub_exam_module_by_id=EXAM_MAP,
        claim=False,
    )
    assert hub == HUB_L


def test_reading_and_speaking_unchanged_for_gt_user():
    assert (
        pick_hub_for_slot(
            skill="reading",
            hub_ids=[HUB_R],
            hub_to_set=SET_MAP,
            user_exam_module="general_training",
            hub_exam_module_by_id=EXAM_MAP,
            claim=False,
        )
        == HUB_R
    )
    assert (
        pick_hub_for_slot(
            skill="speaking",
            hub_ids=[HUB_S],
            hub_to_set=SET_MAP,
            user_exam_module="general_training",
            hub_exam_module_by_id=EXAM_MAP,
            claim=False,
        )
        == HUB_S
    )


# ── Existing plans sticky ───────────────────────────────────────────────────


def _mini_plan(*, writing_hub: str | None, day: date | None = None) -> dict:
    d = (day or (date.today() + timedelta(days=2))).isoformat()
    tasks = [
        {
            "id": "w1",
            "module": "writing",
            "task_type": "practice",
            "hub_id": writing_hub,
            "status": "pending",
        },
        {
            "id": "l1",
            "module": "listening",
            "task_type": "practice",
            "hub_id": HUB_L,
            "status": "pending",
        },
    ]
    return {
        "weeks": [{"id": "w1", "days": [{"date": d, "tasks": tasks}]}],
        "assigned_hub_ids": [h for h in [writing_hub, HUB_L] if h],
        "prep_start": date.today().isoformat(),
        "exam_date": (date.today() + timedelta(days=30)).isoformat(),
    }


def test_existing_writing_assignment_not_rewritten_on_track_mismatch():
    """Sticky: existing GT hub stays even if user is now academic."""
    plan = _mini_plan(writing_hub=HUB_GT)
    out = rewrite_plan_hubs(
        plan,
        ordered_ids={
            "writing": [HUB_ACAD, HUB_BOTH],
            "listening": [HUB_L],
            "reading": [],
            "speaking": [],
        },
        hub_to_set=SET_MAP,
        user_exam_module="academic",
        hub_exam_module_by_id=EXAM_MAP,
        claim=False,
        today=date.today(),
    )
    day = out["weeks"][0]["days"][0]
    writing_hubs = [
        t["hub_id"] for t in day["tasks"] if t.get("module") == "writing"
    ]
    listening_hubs = [
        t["hub_id"] for t in day["tasks"] if t.get("module") == "listening"
    ]
    assert writing_hubs == [HUB_GT]
    assert listening_hubs == [HUB_L]


def test_empty_writing_slot_fills_only_compatible():
    plan = _mini_plan(writing_hub=None)
    out = rewrite_plan_hubs(
        plan,
        ordered_ids={
            "writing": [HUB_GT, HUB_ACAD, HUB_BOTH],
            "listening": [HUB_L],
            "reading": [],
            "speaking": [],
        },
        hub_to_set=SET_MAP,
        user_exam_module="academic",
        hub_exam_module_by_id=EXAM_MAP,
        claim=False,
        today=date.today(),
    )
    day = out["weeks"][0]["days"][0]
    writing_hub = next(
        t["hub_id"] for t in day["tasks"] if t.get("module") == "writing"
    )
    assert writing_hub == HUB_ACAD


def test_null_track_leaves_empty_writing_slot():
    plan = _mini_plan(writing_hub=None)
    out = rewrite_plan_hubs(
        plan,
        ordered_ids={
            "writing": [HUB_ACAD, HUB_BOTH],
            "listening": [HUB_L],
            "reading": [],
            "speaking": [],
        },
        hub_to_set=SET_MAP,
        user_exam_module=None,
        hub_exam_module_by_id=EXAM_MAP,
        claim=False,
        today=date.today(),
    )
    day = out["weeks"][0]["days"][0]
    writing_hub = next(
        t["hub_id"] for t in day["tasks"] if t.get("module") == "writing"
    )
    assert writing_hub is None
    listening_hub = next(
        t["hub_id"] for t in day["tasks"] if t.get("module") == "listening"
    )
    assert listening_hub == HUB_L


# ── Fan-out ─────────────────────────────────────────────────────────────────


def _active_profile(plan: dict) -> dict:
    return {
        "user_id": str(USER),
        "study_plan": plan,
        "exam_date": (date.today() + timedelta(days=40)).isoformat(),
        "prep_start": date.today().isoformat(),
        "plan_tier": "full_skill_program",
        "updated_at": "2026-08-21T00:00:00+00:00",
    }


def test_offer_writing_skips_mismatched_track():
    plan = _mini_plan(writing_hub=None)
    with (
        patch(
            "app.practice.catalog_jobs.fetch_profile_row",
            return_value=_active_profile(plan),
        ),
        patch("app.practice.catalog_jobs.get_user_progress_map", return_value={}),
    ):
        out = offer_published_set(
            user_id=USER,
            practice_set_id="set-gt",
            hub_id=HUB_GT,
            skill="writing",
            set_exam_module="general_training",
            user_exam_module="academic",
        )
    assert out == "ineligible"


def test_offer_writing_needs_track_when_null():
    plan = _mini_plan(writing_hub=None)
    with (
        patch(
            "app.practice.catalog_jobs.fetch_profile_row",
            return_value=_active_profile(plan),
        ),
        patch("app.practice.catalog_jobs.get_user_progress_map", return_value={}),
    ):
        out = offer_published_set(
            user_id=USER,
            practice_set_id="set-acad",
            hub_id=HUB_ACAD,
            skill="writing",
            set_exam_module="academic",
            user_exam_module=None,
        )
    assert out == "needs_writing_track"


def test_offer_listening_ignores_exam_module():
    """L/R/S fan-out must not apply Writing track filtering."""
    plan = _mini_plan(writing_hub=None)
    # Empty listening day needed — reuse helper with listening empty.
    d = (date.today() + timedelta(days=3)).isoformat()
    plan = {
        "weeks": [
            {
                "id": "w1",
                "days": [
                    {
                        "date": d,
                        "tasks": [
                            {
                                "id": "l1",
                                "module": "listening",
                                "task_type": "practice",
                                "hub_id": None,
                                "status": "pending",
                            }
                        ],
                    }
                ],
            }
        ],
        "assigned_hub_ids": [],
        "prep_start": date.today().isoformat(),
        "exam_date": (date.today() + timedelta(days=30)).isoformat(),
    }
    with (
        patch(
            "app.practice.catalog_jobs.fetch_profile_row",
            return_value=_active_profile(plan),
        ),
        patch("app.practice.catalog_jobs.get_user_progress_map", return_value={}),
        patch(
            "app.practice.catalog_jobs.try_claim_practice_assignment",
            return_value="claimed",
        ),
        patch("app.practice.catalog_jobs._persist_plan", return_value=True),
        patch("app.practice.catalog_jobs.invalidate_learning_profile_cache"),
    ):
        out = offer_published_set(
            user_id=USER,
            practice_set_id="set-l",
            hub_id=HUB_L,
            skill="listening",
            user_exam_module=None,  # would block Writing; must not block Listening
        )
    assert out == "filled"


# ── Writing Skill isolation ─────────────────────────────────────────────────


def test_writing_skill_still_uses_usage_exam_module_not_users():
    """Regression: FSP users.exam_module must not drive Writing Skill course."""
    from app.practice.writing_skill_course import list_writing_skill_hub_rows

    usage_track = "general_training"
    ctx = {
        "subscription_id": "sub-1",
        "plan_id": "plan-ws",
        "usage": {"id": "u1", "exam_module": usage_track},
        "exam_module": usage_track,
    }
    hub_row = {
        "id": "hub-ws-gt",
        "skill": "writing",
        "status": "published",
        "practice_set_id": "set-ws",
    }
    with (
        patch(
            "app.practice.writing_skill_course.get_writing_skill_course_context",
            return_value=ctx,
        ),
        patch(
            "app.practice.writing_skill_course.list_writing_skill_program_items",
            return_value=[
                {
                    "item_id": "hub-ws-gt",
                    "exam_module": "general_training",
                    "sort_order": 1,
                    "is_active": True,
                    "item_type": "practice_hub",
                }
            ],
        ) as list_items,
        patch("app.practice.repository.get_hub_by_id", return_value=hub_row),
        patch("app.practice.repository.is_hub_assignable", return_value=True),
        patch(
            "app.practice.repository._flatten_hub_row",
            side_effect=lambda r: {
                "id": r["id"],
                "skill": "writing",
                "status": "published",
            },
        ),
        # Even if FSP profile says academic, Writing Skill must ignore it.
        patch(
            "app.payments.repository.get_user_exam_module",
            return_value="academic",
        ),
    ):
        rows = list_writing_skill_hub_rows(user_id=USER)

    list_items.assert_called_once_with(
        plan_id="plan-ws", exam_module="general_training"
    )
    assert rows[0]["_program_exam_module"] == "general_training"
