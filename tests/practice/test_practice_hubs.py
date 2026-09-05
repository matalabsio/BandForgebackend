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
        "set_id": f"set-{bank}-{set_num}",
        "estimated_min": 25,
        "sort_order": bank * 10 + set_num,
        "practice_prompt": "Practice",
        "practice_sets": {
            "id": f"set-{bank}-{set_num}",
            "set_number": set_num,
            "title": f"{skill.title()} Set {bank}.{set_num}",
            "status": "published",
            "difficulty": "medium",
            "practice_banks": {
                "skill": skill,
                "bank_number": bank,
                "title": f"{skill.title()} Bank {bank}",
            },
        },
    }


def test_has_full_skill_program_true():
    with patch(
        "app.payments.repository.list_active_subscriptions",
        return_value=[{"plans": {"slug": "full_skill_program"}}],
    ):
        assert has_full_skill_program(USER_ID) is True


def test_has_full_skill_program_false_wrong_plan():
    with patch(
        "app.payments.repository.list_active_subscriptions",
        return_value=[{"plans": {"slug": "premium_monthly"}}],
    ):
        assert has_full_skill_program(USER_ID) is False


def test_has_full_skill_program_false_no_sub():
    with patch(
        "app.payments.repository.list_active_subscriptions",
        return_value=[],
    ):
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


def test_assert_hub_accessible_allows_any_assignable_hub():
    """Phase 1: soft-repeat may open non-sequential hubs — no hard sequential lock."""
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
        patch("app.practice.service.repository.is_hub_assignable", return_value=True),
        patch("app.practice.service.repository.get_user_progress_map", return_value={}),
        patch(
            "app.practice.service.resolve_practice_skill_access",
            return_value="fsp",
        ),
    ):
        flat = service.assert_hub_accessible(user_id=USER_ID, hub_id="h2")
    assert flat["id"] == "h2"


def test_list_hubs_marks_accessible_flag():
    hubs = [
        _hub_row("listening", "h1", 1, 1),
        _hub_row("listening", "h2", 1, 2),
    ]
    with (
        patch("app.practice.service.repository.list_hubs_for_skill", return_value=hubs),
        patch("app.practice.service.repository.get_user_progress_map", return_value={}),
        patch(
            "app.practice.service.resolve_practice_skill_access",
            return_value="fsp",
        ),
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
        patch(
            "app.practice.service.resolve_practice_skill_access",
            return_value="fsp",
        ),
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
        patch("app.practice.service.repository.is_hub_assignable", return_value=True),
        patch("app.practice.service.repository.list_hubs_for_skill", return_value=[row]),
        patch("app.practice.service.repository.get_user_progress_map", return_value={}),
        patch(
            "app.practice.service.resolve_practice_skill_access",
            return_value="fsp",
        ),
        patch(
            "app.practice.catalog.get_ordered_hub_ids_by_skill",
            return_value={"listening": [hub_id]},
        ),
        patch(
            "app.practice.service.repository.upsert_hub_completed",
            return_value={"status": "completed", "completed_at": "2026-07-17T10:00:00+00:00"},
        ),
        patch("app.practice.service._skill_progress_for_access_mode") as mock_prog,
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
        used_hub_ids: set[str] | None = None,
        used_set_ids: set[str] | None = None,
        hub_to_set: dict[str, str] | None = None,
        **_kwargs,
    ) -> str | None:
        from app.practice.assignment import pick_unused_hub

        ids = fake_catalog.get(skill) or []
        mapping = hub_to_set or {h: f"set-{h}" for h in ids}
        return pick_unused_hub(
            hub_ids=ids,
            used_hub_ids=used_hub_ids,
            used_set_ids=used_set_ids,
            hub_to_set=mapping,
        )

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
    practice = next(t for t in plan.weeks[0].days[0].tasks if t.task_type == "practice")
    assert practice.href.startswith("/practice/") or practice.href.startswith("/test/")
    assert "from=plan" in practice.href
    assert "task=practice" in practice.href
    assert not any(t.task_type == "watch" for t in plan.weeks[0].days[0].tasks)


def test_pick_hub_for_slot_does_not_wrap():
    from app.practice.assignment import pick_hub_for_slot

    used_h: set[str] = set()
    used_s: set[str] = set()
    mapping = {"l1": "s1", "l2": "s2", "l3": "s3"}
    hubs = ["l1", "l2", "l3"]
    # former wrap: cursor=1, day=2 → (1+2)%3 = l1. Unique picker never returns used.
    assert (
        pick_hub_for_slot(
            skill="listening",
            hub_ids=hubs,
            hub_to_set=mapping,
            used_hub_ids={"l2", "l3"},
            used_set_ids={"s2", "s3"},
            day_index=2,
            completed_count=1,
        )
        == "l1"
    )
    picks = []
    for _ in range(5):
        picks.append(
            pick_hub_for_slot(
                skill="listening",
                hub_ids=hubs,
                hub_to_set=mapping,
                used_hub_ids=used_h,
                used_set_ids=used_s,
            )
        )
    assert picks == ["l1", "l2", "l3", None, None]


def test_assign_hub_for_day_never_repeats_used():
    from app.practice.assignment import assign_hub_for_day

    hubs = ["a", "b", "c"]
    used: set[str] = set()
    mapping = {"a": "sa", "b": "sb", "c": "sc"}
    assert assign_hub_for_day(hub_ids=hubs, used_hub_ids=used, hub_to_set=mapping) == "a"
    used.add("a")
    assert assign_hub_for_day(hub_ids=hubs, used_hub_ids=used, hub_to_set=mapping) == "b"
    used.update({"a", "b", "c"})
    assert assign_hub_for_day(hub_ids=hubs, used_hub_ids=used, hub_to_set=mapping) is None
    assert assign_hub_for_day(hub_ids=["only"], used_hub_ids={"only"}, hub_to_set={"only": "s"}) is None
    assert assign_hub_for_day(hub_ids=[], used_hub_ids=used) is None


def test_skill_cursor_counts_completed_in_pool():
    from app.practice.assignment import skill_cursor

    progress = {
        "l1": {"status": "completed"},
        "l2": {"status": "completed"},
        "other": {"status": "completed"},
    }
    assert (
        skill_cursor(
            skill="listening",
            progress_map=progress,
            hub_ids=["l1", "l2", "l3"],
        )
        == 2
    )
    assert skill_cursor(skill="listening", progress_map={}, hub_ids=["l1"]) == 0


def test_rewrite_plan_hubs_keeps_assigned_and_fills_empty():
    from datetime import date, timedelta

    from app.practice.assignment import rewrite_plan_hubs

    start = date(2026, 8, 1)
    today = date(2026, 8, 2)
    plan = {
        "prep_start": start.isoformat(),
        "weeks": [
            {
                "id": "w1",
                "label": "Week 1",
                "focus": "x",
                "days": [
                    {
                        "date": start.isoformat(),
                        "label": "Sat",
                        "tasks": [
                            {
                                "id": "t1",
                                "title": "L Watch",
                                "module": "listening",
                                "task_type": "watch",
                                "hub_id": "stale",
                                "href": "/old",
                            },
                            {
                                "id": "t2",
                                "title": "L Practice",
                                "module": "listening",
                                "task_type": "practice",
                                "hub_id": "stale",
                                "href": "/old",
                            },
                        ],
                    },
                    {
                        "date": today.isoformat(),
                        "label": "Sun",
                        "tasks": [
                            {
                                "id": "t3",
                                "title": "L Watch",
                                "module": "listening",
                                "task_type": "watch",
                                "hub_id": "today-assigned",
                                "href": "/old",
                            },
                        ],
                    },
                    {
                        "date": (today + timedelta(days=1)).isoformat(),
                        "label": "Mon",
                        "tasks": [
                            {
                                "id": "t4",
                                "title": "L Watch",
                                "module": "listening",
                                "task_type": "watch",
                                "hub_id": None,
                                "href": "/study-plan/today?skill=listening&unavailable=1",
                            },
                        ],
                    },
                ],
            }
        ],
    }
    out = rewrite_plan_hubs(
        plan,
        ordered_ids={
            "listening": ["L-easy", "L-med", "L-hard"],
            "reading": [],
            "writing": [],
            "speaking": [],
        },
        hub_to_set={
            "stale": "set-stale",
            "today-assigned": "set-today",
            "L-easy": "set-easy",
            "L-med": "set-med",
            "L-hard": "set-hard",
        },
        href_builder=lambda **kw: f"/ok/{kw.get('hub_id')}",
        today=today,
        claim=False,
    )
    d0 = out["weeks"][0]["days"][0]["tasks"]
    d1 = out["weeks"][0]["days"][1]["tasks"]
    d2 = out["weeks"][0]["days"][2]["tasks"]
    assert d0[0]["hub_id"] == "stale"
    assert d0[1]["hub_id"] == "stale"
    assert d1[0]["hub_id"] == "today-assigned"
    assert d2[0]["hub_id"] == "L-easy"
    assert d0[0]["href"] == "/ok/stale"



def test_pick_hub_for_slot_returns_none_when_empty():
    from app.practice.catalog import pick_hub_for_slot

    with patch(
        "app.practice.catalog.get_ordered_question_bank_ids_by_skill",
        return_value={"listening": []},
    ), patch("app.practice.catalog.get_hub_set_ids", return_value={}):
        assert pick_hub_for_slot(skill="listening", day_index=0, completed_count=0) is None


def test_set_content_ok_listening_requires_audio_and_answers():
    from app.practice.repository import _set_content_ok

    sections = [{"id": "s1", "audio_key": "audio/key.mp3", "passage_text": None}]
    qs = {
        "s1": [
            {"prompt": "Q1", "correct_answer": "A", "audio_url": None, "passage_text": None}
        ]
    }
    assert _set_content_ok(skill="listening", sections=sections, questions_by_section=qs)

    bad = {
        "s1": [
            {"prompt": "Q1", "correct_answer": "", "audio_url": None, "passage_text": None}
        ]
    }
    assert not _set_content_ok(skill="listening", sections=sections, questions_by_section=bad)

    no_audio = [{"id": "s1", "audio_key": "", "passage_text": None}]
    assert not _set_content_ok(
        skill="listening", sections=no_audio, questions_by_section=qs
    )


def test_set_content_ok_reading_writing_speaking():
    from app.practice.repository import _set_content_ok

    r_sections = [{"id": "s1", "audio_key": None, "passage_text": "Passage body"}]
    r_qs = {
        "s1": [
            {
                "prompt": "Q1",
                "correct_answer": "TRUE",
                "audio_url": None,
                "passage_text": "Passage body",
            }
        ]
    }
    assert _set_content_ok(skill="reading", sections=r_sections, questions_by_section=r_qs)

    w_sections = [{"id": "s1", "audio_key": None, "passage_text": "Write about X"}]
    assert _set_content_ok(skill="writing", sections=w_sections, questions_by_section={})

    s_qs = {"s1": [{"prompt": "Talk about home", "correct_answer": None, "audio_url": None, "passage_text": None}]}
    assert _set_content_ok(
        skill="speaking",
        sections=[{"id": "s1", "audio_key": None, "passage_text": None}],
        questions_by_section=s_qs,
    )
    video_only = {
        "s1": [
            {
                "prompt": "",
                "options": {"video_url": "bank/set/speaking/part1/clip.mp4"},
                "correct_answer": None,
                "audio_url": None,
                "passage_text": None,
            }
        ]
    }
    assert _set_content_ok(
        skill="speaking",
        sections=[{"id": "s1", "audio_key": None, "passage_text": None}],
        questions_by_section=video_only,
    )


def test_filter_assignable_excludes_draft(monkeypatch):
    from app.practice import repository as repo

    draft = _hub_row("listening", "h-draft", 1, 1)
    draft["practice_sets"]["status"] = "draft"
    published = _hub_row("listening", "h-pub", 1, 2)

    monkeypatch.setattr(
        repo,
        "_assignable_set_ids",
        lambda set_ids, skill_by_set: {str(published["practice_sets"]["id"])},
    )
    out = repo._filter_assignable_hub_rows([draft, published])
    assert len(out) == 1
    assert out[0]["id"] == "h-pub"


def test_assert_hub_accessible_404_when_not_assignable():
    detail = _hub_row("listening", "h1", 1, 1)
    with (
        patch("app.practice.service.repository.get_hub_by_id", return_value=detail),
        patch("app.practice.service.repository.is_hub_assignable", return_value=False),
        patch(
            "app.practice.service.resolve_practice_skill_access",
            return_value="fsp",
        ),
        patch(
            "app.practice.catalog.get_ordered_hub_ids_by_skill",
            return_value={},
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            service.assert_hub_accessible(user_id=USER_ID, hub_id="h1")
    assert exc.value.status_code == 404


def _hub_detail_flat(**overrides: object) -> dict:
    base = {
        "id": "h1",
        "slug": "listening-b1-s1",
        "skill": "listening",
        "bank_number": 1,
        "set_number": 1,
        "title": "Listening Set 1.1",
        "estimated_min": 25,
        "sort_order": 1,
        "intro_stream_uid": None,
        "intro_video_key": None,
        "videos": [
            {
                "title": "Listening intro",
                "url": "https://skill.example/iframe",
                "duration_min": 12,
                "tag": "listening-intro",
                "stream_uid": "skill-uid",
            }
        ],
        "practice_prompt": "",
        "submit_config": {},
    }
    base.update(overrides)
    return base


def test_get_hub_detail_ready_set_uid_uses_signed_set_intro():
    flat = _hub_detail_flat(intro_stream_uid="set-uid-ready")
    with (
        patch(
            "app.practice.service._assert_hub_accessible_with_progress",
            return_value=(flat, {}),
        ),
        patch(
            "app.storage.stream.get_video",
            return_value={"status": {"state": "ready"}},
        ),
        patch("app.storage.stream.create_signed_playback_token", return_value="tok"),
        patch(
            "app.storage.stream.playback_signed_iframe_url",
            return_value="https://signed.example/set-intro",
        ),
        patch("app.admin.stream_videos._customer_code", return_value="customer-test"),
    ):
        out = service.get_hub_detail(user_id=USER_ID, hub_id="h1")
    assert len(out.videos) == 1
    assert out.videos[0].tag == "set-intro"
    assert out.videos[0].stream_uid == "set-uid-ready"
    assert out.videos[0].url == "https://signed.example/set-intro"


def test_get_hub_detail_unready_set_uid_falls_back_to_skill_videos():
    flat = _hub_detail_flat(intro_stream_uid="set-uid-processing")
    with (
        patch(
            "app.practice.service._assert_hub_accessible_with_progress",
            return_value=(flat, {}),
        ),
        patch(
            "app.storage.stream.get_video",
            return_value={"status": {"state": "inprogress"}},
        ),
        patch("app.storage.stream.create_signed_playback_token") as sign,
    ):
        out = service.get_hub_detail(user_id=USER_ID, hub_id="h1")
    sign.assert_not_called()
    assert len(out.videos) == 1
    assert out.videos[0].tag == "listening-intro"
    assert out.videos[0].url == "https://skill.example/iframe"


def test_get_hub_detail_missing_uid_uses_skill_videos():
    flat = _hub_detail_flat()
    with patch(
        "app.practice.service._assert_hub_accessible_with_progress",
        return_value=(flat, {}),
    ):
        out = service.get_hub_detail(user_id=USER_ID, hub_id="h1")
    assert len(out.videos) == 1
    assert out.videos[0].tag == "listening-intro"


def test_get_hub_detail_signed_url_fail_falls_back_to_skill_videos():
    from app.storage.stream import StreamError

    flat = _hub_detail_flat(intro_stream_uid="set-uid-ready")
    with (
        patch(
            "app.practice.service._assert_hub_accessible_with_progress",
            return_value=(flat, {}),
        ),
        patch(
            "app.storage.stream.get_video",
            return_value={"status": {"state": "ready"}},
        ),
        patch(
            "app.storage.stream.create_signed_playback_token",
            side_effect=StreamError("sign failed"),
        ),
        patch("app.admin.stream_videos._customer_code", return_value="customer-test"),
    ):
        out = service.get_hub_detail(user_id=USER_ID, hub_id="h1")
    assert len(out.videos) == 1
    assert out.videos[0].tag == "listening-intro"
