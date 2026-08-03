"""Phase 2 practice hub tests."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.auth.schemas import UserPublic
from app.learning.rules import build_personalized_study_plan
from app.practice.schemas import SkillHubProgressOut
from app.practice import service
from app.security.entitlements import has_full_skill_program, require_full_skill_program

USER_ID = UUID("00000000-0000-4000-8000-0000000000a1")


def _user() -> UserPublic:
    return UserPublic(
        id=USER_ID,
        email="student@example.com",
        full_name="Test Student",
        phone="9876543210",
        target_band=7.0,
    )


def _hub_row(skill: str, hub_id: str, bank: int, set_num: int) -> dict:
    return {
        "id": hub_id,
        "slug": f"{skill}-b{bank}-s{set_num}",
        "estimated_min": 25,
        "sort_order": bank * 10 + set_num,
        "practice_prompt": "Practice",
        "practice_sets": {
            "set_number": set_num,
            "title": f"{skill.title()} Set {bank}.{set_num}",
            "practice_banks": {
                "skill": skill,
                "bank_number": bank,
                "title": f"{skill.title()} Bank {bank}",
            },
        },
    }


def test_has_full_skill_program_true():
    with patch("app.payments.repository.get_active_subscription") as mock_sub:
        mock_sub.return_value = {"plans": {"slug": "full_skill_program"}}
        assert has_full_skill_program(USER_ID) is True


def test_has_full_skill_program_false_wrong_plan():
    with patch("app.payments.repository.get_active_subscription") as mock_sub:
        mock_sub.return_value = {"plans": {"slug": "premium_monthly"}}
        assert has_full_skill_program(USER_ID) is False


def test_has_full_skill_program_false_no_sub():
    with patch("app.payments.repository.get_active_subscription") as mock_sub:
        mock_sub.return_value = None
        assert has_full_skill_program(USER_ID) is False


def test_require_full_skill_program_raises_403():
    with patch("app.security.entitlements.has_full_skill_program", return_value=False):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(require_full_skill_program(_user()))
        assert exc.value.status_code == 403


def test_accessible_hubs_unlock_sequentially():
    hubs = [
        _hub_row("listening", "h1", 1, 1),
        _hub_row("listening", "h2", 1, 2),
        _hub_row("listening", "h3", 1, 3),
    ]
    progress = {"h1": {"status": "completed"}}
    with (
        patch("app.practice.service.repository.list_hubs_for_skill", return_value=hubs),
        patch(
            "app.practice.service.repository.get_user_progress_map",
            return_value=progress,
        ),
    ):
        allowed = service.accessible_hub_ids_for_skill(
            user_id=USER_ID, skill="listening", progress_map=progress
        )
    assert allowed == {"h1", "h2"}


def test_current_hub_id_for_skill_picks_next_incomplete():
    hubs = [
        _hub_row("listening", "h1", 1, 1),
        _hub_row("listening", "h2", 1, 2),
        _hub_row("listening", "h3", 1, 3),
    ]
    progress = {"h1": {"status": "completed"}}
    with (
        patch("app.practice.service.repository.list_hubs_for_skill", return_value=hubs),
        patch(
            "app.practice.service.repository.get_user_progress_map",
            return_value=progress,
        ),
    ):
        assert (
            service.current_hub_id_for_skill(
                user_id=USER_ID, skill="listening", progress_map=progress
            )
            == "h2"
        )


def test_current_hub_id_for_skill_falls_back_to_last_completed():
    hubs = [
        _hub_row("listening", "h1", 1, 1),
        _hub_row("listening", "h2", 1, 2),
    ]
    progress = {"h1": {"status": "completed"}, "h2": {"status": "completed"}}
    with (
        patch("app.practice.service.repository.list_hubs_for_skill", return_value=hubs),
        patch(
            "app.practice.service.repository.get_user_progress_map",
            return_value=progress,
        ),
    ):
        assert (
            service.current_hub_id_for_skill(
                user_id=USER_ID, skill="listening", progress_map=progress
            )
            == "h2"
        )


def test_assert_hub_accessible_blocks_locked_hub():
    hubs = [
        _hub_row("listening", "h1", 1, 1),
        _hub_row("listening", "h2", 1, 2),
    ]
    detail = {
        **hubs[1],
        "set_id": "set-2",
        "videos": [],
        "submit_config": {},
        "practice_sets": hubs[1]["practice_sets"],
    }
    with (
        patch("app.practice.service.repository.get_hub_by_id", return_value=detail),
        patch("app.practice.service.repository.list_hubs_for_skill", return_value=hubs),
        patch("app.practice.service.repository.get_user_progress_map", return_value={}),
    ):
        with pytest.raises(HTTPException) as exc:
            service.assert_hub_accessible(user_id=USER_ID, hub_id="h2")
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "hub_locked"


def test_list_hubs_marks_accessible_flag():
    hubs = [
        _hub_row("listening", "h1", 1, 1),
        _hub_row("listening", "h2", 1, 2),
    ]
    with (
        patch("app.practice.service.repository.list_hubs_for_skill", return_value=hubs),
        patch("app.practice.service.repository.get_user_progress_map", return_value={}),
    ):
        out = service.list_hubs_with_progress(user_id=USER_ID, skill="listening")
    assert out[0].accessible is True
    assert out[1].accessible is False
    assert out[1].locked_reason


def test_skill_progress_full_catalog_total():
    """Phase 5: 12 hubs per skill; required_for_mock stays 12; unlock at 12/12."""
    hubs = [_hub_row("writing", f"h{i}", (i - 1) // 3 + 1, (i - 1) % 3 + 1) for i in range(1, 13)]
    progress_11 = {
        str(h["id"]): {"status": "completed"} for h in hubs[:11]
    }
    progress_12 = {
        str(h["id"]): {"status": "completed"} for h in hubs
    }
    with (
        patch("app.practice.service.repository.list_hubs_for_skill", return_value=hubs),
        patch(
            "app.practice.service.repository.get_user_progress_map",
            return_value=progress_11,
        ),
        patch(
            "app.practice.service.repository.get_skill_full_mock",
            return_value={"unlock_requires_sets": 12, "mock_test_id": "mock-1"},
        ),
    ):
        prog = service.skill_progress(user_id=USER_ID, skill="writing")
        assert prog.total_count == 12
        assert prog.required_for_mock == 12
        assert prog.mock_unlocked is False

        with patch(
            "app.practice.service.repository.get_user_progress_map",
            return_value=progress_12,
        ):
            prog2 = service.skill_progress(user_id=USER_ID, skill="writing")
            assert prog2.mock_unlocked is True


def test_skill_progress_mock_unlock_pilot_total():
    hubs = [_hub_row("writing", f"h{i}", 1, i) for i in range(1, 7)]
    progress_5 = {
        str(h["id"]): {"status": "completed"} for h in hubs[:5]
    }
    progress_6 = {
        str(h["id"]): {"status": "completed"} for h in hubs
    }
    with (
        patch("app.practice.service.repository.list_hubs_for_skill", return_value=hubs),
        patch(
            "app.practice.service.repository.get_user_progress_map",
            return_value=progress_5,
        ),
        patch(
            "app.practice.service.repository.get_skill_full_mock",
            return_value={"unlock_requires_sets": 12, "mock_test_id": "mock-1"},
        ),
    ):
        prog = service.skill_progress(user_id=USER_ID, skill="writing")
        assert prog.total_count == 6
        assert prog.required_for_mock == 6
        assert prog.mock_unlocked is False

        with patch(
            "app.practice.service.repository.get_user_progress_map",
            return_value=progress_6,
        ):
            prog2 = service.skill_progress(user_id=USER_ID, skill="writing")
            assert prog2.mock_unlocked is True


def test_mock_unlock_independent_per_skill():
    with (
        patch("app.practice.service.skill_progress") as mock_prog,
    ):
        writing = MagicMock()
        writing.mock_unlocked = True
        writing.completed_count = 6
        writing.required_for_mock = 6
        writing.mock_test_id = "m1"

        speaking = MagicMock()
        speaking.mock_unlocked = False
        speaking.completed_count = 2
        speaking.required_for_mock = 6
        speaking.mock_test_id = "m2"

        def side_effect(*, user_id, skill):
            return writing if skill == "writing" else speaking

        mock_prog.side_effect = side_effect
        w = service.mock_unlock_status(user_id=USER_ID, skill="writing")
        s = service.mock_unlock_status(user_id=USER_ID, skill="speaking")
        assert w.unlocked is True
        assert s.unlocked is False


def test_complete_hub_idempotent_shape():
    hub_id = "hub-abc"
    row = _hub_row("listening", hub_id, 1, 1)
    row["videos"] = []
    row["submit_config"] = {}
    with (
        patch("app.practice.service.repository.get_hub_by_id", return_value=row),
        patch("app.practice.service.repository.list_hubs_for_skill", return_value=[row]),
        patch("app.practice.service.repository.get_user_progress_map", return_value={}),
        patch(
            "app.practice.service.repository.upsert_hub_completed",
            return_value={"status": "completed", "completed_at": "2026-07-17T10:00:00+00:00"},
        ),
        patch("app.practice.service.skill_progress") as mock_prog,
    ):
        mock_prog.return_value = SkillHubProgressOut(
            skill="listening",
            completed_count=1,
            total_count=6,
            required_for_mock=6,
            mock_unlocked=False,
            mock_test_id="m1",
        )
        out = service.complete_hub(user_id=USER_ID, hub_id=hub_id)
        assert out.status == "completed"
        assert out.hub_id == hub_id


def test_assert_skill_mock_access_raises_when_locked():
    with patch(
        "app.practice.service.mock_unlock_status",
        return_value=MagicMock(unlocked=False, completed=1, required=6, skill="writing"),
    ):
        with pytest.raises(HTTPException) as exc:
            service.assert_skill_mock_access(user_id=USER_ID, skill="writing")
        assert exc.value.status_code == 403


def test_build_personalized_study_plan_assigns_hub_ids():
    today = date.today()
    exam = today + timedelta(days=6)
    bands = {"listening": 4.0, "reading": 4.0, "writing": 2.0, "speaking": 2.0}
    fake_catalog = {
        "listening": ["l1", "l2"],
        "reading": ["r1"],
        "writing": ["w1"],
        "speaking": ["s1"],
    }

    def fake_pick(
        *,
        skill: str,
        day_index: int,
        slot_index: int = 0,
        completed_count: int | None = None,
    ) -> str | None:
        ids = fake_catalog.get(skill) or []
        if not ids:
            return None
        if completed_count is not None:
            idx = min(max(completed_count, 0) + max(day_index, 0), len(ids) - 1)
            return ids[idx]
        return ids[(day_index + slot_index) % len(ids)]

    with patch("app.practice.catalog.pick_hub_for_slot", side_effect=fake_pick):
        plan = build_personalized_study_plan(
            bands=bands,
            target=7.0,
            exam_date=exam,
            prep_start=today,
        )

    hub_ids = [t.hub_id for t in plan.weeks[0].days[0].tasks if t.hub_id]
    assert hub_ids
    assert all(isinstance(h, str) for h in hub_ids)
    assert plan.assigned_hub_ids
    watch = next(t for t in plan.weeks[0].days[0].tasks if t.task_type == "watch")
    assert watch.href.startswith("/practice/")
    assert "from=plan" in watch.href
    assert "task=watch" in watch.href


def test_pick_hub_for_slot_progress_aware():
    from app.practice.catalog import pick_hub_for_slot

    with patch(
        "app.practice.catalog.get_ordered_hub_ids_by_skill",
        return_value={"listening": ["l1", "l2", "l3"]},
    ):
        assert pick_hub_for_slot(skill="listening", day_index=0, completed_count=1) == "l2"
        assert pick_hub_for_slot(skill="listening", day_index=1, completed_count=1) == "l3"
        assert pick_hub_for_slot(skill="listening", day_index=5, completed_count=2) == "l3"
