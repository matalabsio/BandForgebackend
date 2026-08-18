"""Tests for admin question bank + practice hub exercise wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.admin.schemas import (
    ListeningBuilderQuestionIn,
    ListeningBuilderSaveRequest,
    QuestionBankCreateSetRequest,
    ReadingBuilderQuestionIn,
    ReadingBuilderSaveRequest,
)
from app.admin import question_bank as qb


SET_ID = UUID("11111111-1111-4111-8111-111111111111")
ADMIN_ID = UUID("22222222-2222-4222-8222-222222222222")
HUB_ID = "33333333-3333-4333-8333-333333333333"
USER_ID = UUID("44444444-4444-4444-8444-444444444444")
BANK_ID = "55555555-5555-4555-8555-555555555555"


def test_bank_href_and_module_fallback():
    assert qb._bank_href("listening", HUB_ID) == {
        "type": "bank",
        "module": "listening",
        "href": f"/practice/listening/{HUB_ID}/exercise",
    }
    assert "/test/writing/task/1" in qb._module_href("writing")["href"]


def test_save_bank_listening_writes_section_and_questions():
    body = ListeningBuilderSaveRequest(
        audio_key="bank/x/listening/part1/audio.mp3",
        instructions="Listen carefully",
        questions=[
            ListeningBuilderQuestionIn(
                question_type="Note completion",
                prompt="Name?",
                correct_answer="Ann",
                alt_answers=[],
            )
        ],
    )
    with (
        patch(
            "app.admin.question_bank._load_set_skill",
            return_value=({"id": str(SET_ID)}, "listening"),
        ),
        patch(
            "app.admin.question_bank._upsert_section",
            return_value="55555555-5555-4555-8555-555555555555",
        ) as upsert,
        patch("app.admin.question_bank._replace_questions") as replace,
        patch("app.admin.question_bank.refresh_hub_submit_configs") as refresh,
        patch("app.admin.question_bank.log_admin_action"),
        patch("app.admin.question_bank.get_supabase", return_value=MagicMock()),
    ):
        res = qb.save_bank_listening(
            set_id=SET_ID, part=1, body=body, admin_id=ADMIN_ID
        )
    assert res.ok is True
    assert res.questions_written == 1
    upsert.assert_called_once()
    replace.assert_called_once()
    refresh.assert_called_once_with(practice_set_id=SET_ID, skill="listening")


def test_save_bank_listening_rejects_wrong_skill():
    sb = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(
        data=[{"id": str(SET_ID), "practice_banks": {"skill": "reading"}}]
    )
    sb.table.return_value = chain
    with patch("app.admin.question_bank.get_supabase", return_value=sb):
        with pytest.raises(HTTPException) as exc:
            qb.save_bank_listening(
                set_id=SET_ID,
                part=1,
                body=ListeningBuilderSaveRequest(
                    audio_key="k",
                    questions=[
                        ListeningBuilderQuestionIn(
                            question_type="Note completion",
                            prompt="Q",
                            correct_answer="A",
                            alt_answers=[],
                        )
                    ],
                ),
                admin_id=ADMIN_ID,
            )
    assert exc.value.status_code == 400


def test_start_hub_exercise_returns_questions():
    from app.practice import service

    hub_row = {
        "id": HUB_ID,
        "slug": "listening-b1-s1",
        "set_id": str(SET_ID),
        "practice_prompt": "",
        "submit_config": {},
        "estimated_min": 25,
        "sort_order": 1,
        "videos": [],
        "practice_sets": {
            "id": str(SET_ID),
            "set_number": 1,
            "title": "Listening Set 1.1",
            "practice_banks": {"skill": "listening", "bank_number": 1, "title": "L1"},
        },
    }
    sb = MagicMock()

    def table(name: str):
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.order.return_value = m
        m.update.return_value = m
        m.insert.return_value = m
        m.limit.return_value = m
        if name == "bank_sections":
            m.execute.return_value = MagicMock(
                data=[
                    {
                        "id": "55555555-5555-4555-8555-555555555555",
                        "part": 1,
                        "module": "listening",
                        "title": "Part 1",
                        "instructions": "Go",
                        "audio_key": "a.mp3",
                        "passage_text": None,
                        "image_url": None,
                    }
                ]
            )
        elif name == "bank_questions":
            m.execute.return_value = MagicMock(
                data=[
                    {
                        "id": "66666666-6666-4666-8666-666666666666",
                        "question_number": 1,
                        "question_type": "note_completion",
                        "prompt": "Name?",
                        "options": None,
                        "correct_answer": "Ann",
                    }
                ]
            )
        elif name == "practice_exercise_attempts":
            m.execute.return_value = MagicMock(
                data=[{"id": "77777777-7777-4777-8777-777777777777"}]
            )
        else:
            m.execute.return_value = MagicMock(data=[])
        return m

    sb.table.side_effect = table

    with (
        patch("app.practice.service.repository.get_hub_by_id", return_value=hub_row),
        patch("app.practice.service.repository.is_hub_assignable", return_value=True),
        patch(
            "app.practice.service.repository.get_user_progress_map",
            return_value={},
        ),
        patch(
            "app.practice.service.repository.list_hubs_for_skill",
            return_value=[hub_row],
        ),
        patch("app.db.supabase_client.get_supabase", return_value=sb),
        patch("app.cache.hybrid_cache.get_json", return_value=None),
        patch("app.cache.hybrid_cache.set_json"),
    ):
        out = service.start_hub_exercise(user_id=USER_ID, hub_id=HUB_ID)

    assert out.skill == "listening"
    assert out.part == 1
    assert len(out.section.questions) == 1
    assert out.section.questions[0].correct_answer is None
    assert out.section.audio_url == (
        f"/api/practice/hubs/{HUB_ID}/exercise/{out.attempt_id}/part-audio"
    )
    assert out.section.questions[0].audio_url == out.section.audio_url
    assert out.section.questions[0].video_url is None


def _speaking_hub_row() -> dict:
    return {
        "id": HUB_ID,
        "slug": "speaking-b1-s1",
        "set_id": str(SET_ID),
        "practice_prompt": "",
        "submit_config": {},
        "estimated_min": 25,
        "sort_order": 1,
        "videos": [],
        "practice_sets": {
            "id": str(SET_ID),
            "set_number": 1,
            "title": "Speaking Set 1.1",
            "practice_banks": {"skill": "speaking", "bank_number": 1, "title": "S1"},
        },
    }


def _start_exercise_supabase(*, questions: list[dict], module: str = "speaking"):
    sb = MagicMock()

    def table(name: str):
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.order.return_value = m
        m.update.return_value = m
        m.insert.return_value = m
        m.limit.return_value = m
        if name == "bank_sections":
            m.execute.return_value = MagicMock(
                data=[
                    {
                        "id": "55555555-5555-4555-8555-555555555555",
                        "part": 1,
                        "module": module,
                        "title": "Part 1",
                        "instructions": None,
                        "audio_key": None,
                        "passage_text": None,
                        "image_url": None,
                    }
                ]
            )
        elif name == "bank_questions":
            m.execute.return_value = MagicMock(data=questions)
        elif name == "practice_exercise_attempts":
            m.execute.return_value = MagicMock(
                data=[{"id": "77777777-7777-4777-8777-777777777777"}]
            )
        else:
            m.execute.return_value = MagicMock(data=[])
        return m

    sb.table.side_effect = table
    return sb


def test_start_hub_exercise_signs_speaking_r2_video():
    from app.practice import service

    hub_row = _speaking_hub_row()
    sb = _start_exercise_supabase(
        questions=[
            {
                "id": "66666666-6666-4666-8666-666666666666",
                "question_number": 1,
                "question_type": "speaking_part1",
                "prompt": "Tell me about yourself",
                "options": {
                    "kind": "question",
                    "video_url": "bank/set/speaking/part1/clip.mp4",
                },
                "correct_answer": None,
            },
            {
                "id": "88888888-8888-4888-8888-888888888888",
                "question_number": 2,
                "question_type": "speaking_part1",
                "prompt": "What is best about your hometown",
                "options": {"kind": "question"},
                "correct_answer": None,
            },
        ]
    )

    with (
        patch("app.practice.service.repository.get_hub_by_id", return_value=hub_row),
        patch("app.practice.service.repository.is_hub_assignable", return_value=True),
        patch(
            "app.practice.service.repository.get_user_progress_map",
            return_value={},
        ),
        patch(
            "app.practice.service.repository.list_hubs_for_skill",
            return_value=[hub_row],
        ),
        patch("app.db.supabase_client.get_supabase", return_value=sb),
        patch("app.cache.hybrid_cache.get_json", return_value=None),
        patch("app.cache.hybrid_cache.set_json"),
        patch(
            "app.storage.r2.generate_signed_url",
            return_value="https://signed.example/clip.mp4",
        ) as sign,
    ):
        out = service.start_hub_exercise(user_id=USER_ID, hub_id=HUB_ID)

    assert out.skill == "speaking"
    assert out.section.questions[0].video_url == "https://signed.example/clip.mp4"
    assert out.section.questions[1].video_url is None
    sign.assert_called_once_with("bank/set/speaking/part1/clip.mp4")


def test_start_hub_exercise_speaking_without_video_key():
    from app.practice import service

    hub_row = _speaking_hub_row()
    sb = _start_exercise_supabase(
        questions=[
            {
                "id": "66666666-6666-4666-8666-666666666666",
                "question_number": 1,
                "question_type": "speaking_part1",
                "prompt": "Tell me about yourself",
                "options": {"kind": "question", "video_url": ""},
                "correct_answer": None,
            }
        ]
    )

    with (
        patch("app.practice.service.repository.get_hub_by_id", return_value=hub_row),
        patch("app.practice.service.repository.is_hub_assignable", return_value=True),
        patch(
            "app.practice.service.repository.get_user_progress_map",
            return_value={},
        ),
        patch(
            "app.practice.service.repository.list_hubs_for_skill",
            return_value=[hub_row],
        ),
        patch("app.db.supabase_client.get_supabase", return_value=sb),
        patch("app.cache.hybrid_cache.get_json", return_value=None),
        patch("app.cache.hybrid_cache.set_json"),
        patch("app.storage.r2.generate_signed_url") as sign,
    ):
        out = service.start_hub_exercise(user_id=USER_ID, hub_id=HUB_ID)

    assert out.section.questions[0].video_url is None
    sign.assert_not_called()


def test_score_user_answer_strips_exam_mcq_token():
    from app.practice.service import _score_user_answer

    assert _score_user_answer("0::A") == "A"
    assert _score_user_answer("15") == "15"
    assert _score_user_answer("semester") == "semester"


def test_save_bank_reading_requires_reading_set():
    sb = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(
        data=[{"id": str(SET_ID), "practice_banks": {"skill": "listening"}}]
    )
    sb.table.return_value = chain
    with patch("app.admin.question_bank.get_supabase", return_value=sb):
        with pytest.raises(HTTPException) as exc:
            qb.save_bank_reading(
                set_id=SET_ID,
                part=1,
                body=ReadingBuilderSaveRequest(
                    passage_text="Hello passage long enough",
                    questions=[
                        ReadingBuilderQuestionIn(
                            question_type="True / False / Not Given",
                            prompt="Claim?",
                            correct_answer="True",
                            alt_answers=[],
                        )
                    ],
                ),
                admin_id=ADMIN_ID,
            )
    assert exc.value.status_code == 400


def test_create_question_bank_set_uses_custom_bank_and_hub():
    body = QuestionBankCreateSetRequest(
        skill="listening",
        title="Named practice set",
        description="For note completion",
        status="draft",
    )
    sb = MagicMock()
    caches: dict[str, MagicMock] = {}
    counters = {"banks": 0, "sets": 0, "hubs": 0}

    def make_chain(name: str) -> MagicMock:
        if name in caches:
            return caches[name]
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.order.return_value = m
        m.limit.return_value = m
        m.insert.return_value = m
        m.update.return_value = m

        def exec_fn():
            if name == "practice_banks":
                counters["banks"] += 1
                if counters["banks"] == 1:
                    return MagicMock(data=[])
                return MagicMock(data=[{"id": BANK_ID}])
            if name == "practice_sets":
                counters["sets"] += 1
                if counters["sets"] == 1:
                    return MagicMock(data=[{"set_number": 2}])
                return MagicMock(
                    data=[
                        {
                            "id": str(SET_ID),
                            "set_number": 3,
                            "title": "Named practice set",
                        }
                    ]
                )
            if name == "practice_hubs":
                counters["hubs"] += 1
                if counters["hubs"] == 1:
                    return MagicMock(data=[{"sort_order": 10}])
                return MagicMock(
                    data=[{"id": HUB_ID, "slug": "listening-custom-abcd1234"}]
                )
            return MagicMock(data=[])

        m.execute.side_effect = exec_fn
        caches[name] = m
        return m

    sb.table.side_effect = make_chain

    with (
        patch("app.admin.question_bank.get_supabase", return_value=sb),
        patch("app.admin.question_bank.log_admin_action") as log,
        patch("app.admin.question_bank.videos_for_skill", return_value=[]) as seed,
    ):
        res = qb.create_question_bank_set(body=body, admin_id=ADMIN_ID)

    assert res.set_id == SET_ID
    assert res.skill == "listening"
    assert res.title == "Named practice set"
    assert res.hub_id == UUID(HUB_ID)
    assert res.parts == qb.MAX_PARTS["listening"]
    assert res.bank_number == qb.CUSTOM_BANK_NUMBER
    assert res.set_number == 3
    assert res.status == "draft"
    log.assert_called_once()
    seed.assert_called_once_with("listening")
    insert_payload = caches["practice_hubs"].insert.call_args.args[0]
    assert insert_payload["videos"] == []
    assert insert_payload["submit_config"] == {}
    caches["practice_hubs"].update.assert_called()
    update_payload = caches["practice_hubs"].update.call_args.args[0]
    assert update_payload["submit_config"] == qb._bank_href("listening", HUB_ID)


def test_create_question_bank_set_seeds_skill_intro_video():
    body = QuestionBankCreateSetRequest(skill="listening", title="With intro")
    seeded = [
        {
            "title": "Listening intro",
            "url": "https://customer-x.cloudflarestream.com/abc/iframe",
            "duration_min": 12,
            "tag": "listening-intro",
            "stream_uid": "abc",
        }
    ]
    sb = MagicMock()
    caches: dict[str, MagicMock] = {}
    counters = {"banks": 0, "sets": 0, "hubs": 0}

    def make_chain(name: str) -> MagicMock:
        if name in caches:
            return caches[name]
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.order.return_value = m
        m.limit.return_value = m
        m.insert.return_value = m
        m.update.return_value = m

        def exec_fn():
            if name == "practice_banks":
                counters["banks"] += 1
                if counters["banks"] == 1:
                    return MagicMock(data=[])
                return MagicMock(data=[{"id": BANK_ID}])
            if name == "practice_sets":
                counters["sets"] += 1
                if counters["sets"] == 1:
                    return MagicMock(data=[])
                return MagicMock(
                    data=[{"id": str(SET_ID), "set_number": 1, "title": "With intro"}]
                )
            if name == "practice_hubs":
                counters["hubs"] += 1
                if counters["hubs"] == 1:
                    return MagicMock(data=[])
                return MagicMock(data=[{"id": HUB_ID}])
            return MagicMock(data=[])

        m.execute.side_effect = exec_fn
        caches[name] = m
        return m

    sb.table.side_effect = make_chain

    with (
        patch("app.admin.question_bank.get_supabase", return_value=sb),
        patch("app.admin.question_bank.log_admin_action"),
        patch("app.admin.question_bank.videos_for_skill", return_value=seeded),
    ):
        res = qb.create_question_bank_set(body=body, admin_id=ADMIN_ID)

    assert res.set_id == SET_ID
    insert_payload = caches["practice_hubs"].insert.call_args.args[0]
    assert insert_payload["videos"] == seeded
    assert len(insert_payload["videos"]) == 1


def test_create_question_bank_set_reuses_existing_custom_bank():
    body = QuestionBankCreateSetRequest(skill="reading", title="R custom")
    sb = MagicMock()
    caches: dict[str, MagicMock] = {}
    counters = {"sets": 0, "hubs": 0}

    def make_chain(name: str) -> MagicMock:
        if name in caches:
            return caches[name]
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.order.return_value = m
        m.limit.return_value = m
        m.insert.return_value = m
        m.update.return_value = m

        def exec_fn():
            if name == "practice_banks":
                return MagicMock(data=[{"id": BANK_ID}])
            if name == "practice_sets":
                counters["sets"] += 1
                if counters["sets"] == 1:
                    return MagicMock(data=[])
                return MagicMock(data=[{"id": str(SET_ID), "set_number": 1}])
            if name == "practice_hubs":
                counters["hubs"] += 1
                if counters["hubs"] == 1:
                    return MagicMock(data=[])
                return MagicMock(data=[{"id": HUB_ID}])
            return MagicMock(data=[])

        m.execute.side_effect = exec_fn
        caches[name] = m
        return m

    sb.table.side_effect = make_chain
    with (
        patch("app.admin.question_bank.get_supabase", return_value=sb),
        patch("app.admin.question_bank.log_admin_action"),
        patch("app.admin.question_bank.videos_for_skill", return_value=[]),
    ):
        res = qb.create_question_bank_set(body=body, admin_id=ADMIN_ID)
    assert res.set_number == 1
    assert res.parts == qb.MAX_PARTS["reading"]
    assert res.skill == "reading"
    caches["practice_hubs"].update.assert_called()
    update_payload = caches["practice_hubs"].update.call_args.args[0]
    assert update_payload["submit_config"] == qb._bank_href("reading", HUB_ID)


def test_create_question_bank_set_rejects_published_without_content():
    body = QuestionBankCreateSetRequest(
        skill="listening",
        title="Too early",
        status="published",
    )
    with pytest.raises(HTTPException) as exc:
        qb.create_question_bank_set(body=body, admin_id=ADMIN_ID)
    assert exc.value.status_code == 400
    assert "draft" in str(exc.value.detail).lower()


def test_bank_publish_blockers_listening_missing_audio_and_answers():
    sb = MagicMock()

    def table(name: str):
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.in_.return_value = m
        m.order.return_value = m
        if name == "bank_sections":
            m.execute.return_value = MagicMock(
                data=[
                    {
                        "id": "sec-1",
                        "part": 1,
                        "audio_key": None,
                        "passage_text": None,
                        "module": "listening",
                    }
                ]
            )
        elif name == "bank_questions":
            m.execute.return_value = MagicMock(
                data=[
                    {
                        "id": "q1",
                        "section_id": "sec-1",
                        "prompt": "Q",
                        "passage_text": None,
                        "audio_url": None,
                        "correct_answer": "",
                    }
                ]
            )
        else:
            m.execute.return_value = MagicMock(data=[])
        return m

    sb.table.side_effect = table
    with patch("app.admin.question_bank.get_supabase", return_value=sb):
        blockers = qb.bank_publish_blockers(set_id=SET_ID, skill="listening")
    assert any("audio" in b.lower() for b in blockers)
    assert any("correct answer" in b.lower() for b in blockers)


def test_bank_publish_blockers_writing_requires_prompt():
    sb = MagicMock()

    def table(name: str):
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.in_.return_value = m
        m.order.return_value = m
        m.execute.return_value = MagicMock(data=[])
        return m

    sb.table.side_effect = table
    with patch("app.admin.question_bank.get_supabase", return_value=sb):
        blockers = qb.bank_publish_blockers(set_id=SET_ID, skill="writing")
    assert any("prompt" in b.lower() for b in blockers)


def test_patch_question_bank_set_status_blocks_incomplete_publish():
    from app.admin.schemas import PatchQuestionBankSetStatusRequest

    sb = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.update.return_value = chain
    chain.execute.return_value = MagicMock(
        data=[
            {
                "id": str(SET_ID),
                "status": "draft",
                "practice_banks": {"skill": "writing", "bank_number": 5},
            }
        ]
    )
    sb.table.return_value = chain

    with (
        patch("app.admin.question_bank.get_supabase", return_value=sb),
        patch(
            "app.admin.question_bank.bank_publish_blockers",
            return_value=["Writing: task prompt is required."],
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            qb.patch_question_bank_set_status(
                set_id=SET_ID,
                body=PatchQuestionBankSetStatusRequest(status="published"),
                admin_id=ADMIN_ID,
            )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "publish_blocked"


def test_set_intro_stream_uid_updates_only_that_set():
    other_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    store = {
        str(SET_ID): {"id": str(SET_ID), "intro_stream_uid": None},
        str(other_id): {"id": str(other_id), "intro_stream_uid": "keep-me"},
    }

    class _Chain:
        def __init__(self) -> None:
            self._id: str | None = None
            self._payload: dict | None = None

        def update(self, payload):
            self._payload = payload
            return self

        def eq(self, _col, value):
            self._id = str(value)
            return self

        def execute(self):
            row = store.get(self._id or "")
            if not row or not self._payload:
                return MagicMock(data=[])
            row.update(self._payload)
            return MagicMock(data=[dict(row)])

    sb = MagicMock()
    sb.table.return_value = _Chain()
    with (
        patch("app.admin.question_bank.get_supabase", return_value=sb),
        patch("app.practice.repository.clear_hub_list_cache"),
        patch("app.cache.hybrid_cache.invalidate_prefix"),
    ):
        uid = qb.set_intro_stream_uid(set_id=SET_ID, stream_uid="new-set-uid")

    assert uid == "new-set-uid"
    assert store[str(SET_ID)]["intro_stream_uid"] == "new-set-uid"
    assert store[str(other_id)]["intro_stream_uid"] == "keep-me"
    sb.table.assert_called_with("practice_sets")


def test_bank_watch_complete_does_not_write_stream_videos():
    from app.admin.router import bank_watch_video_complete_route
    from app.auth.schemas import UserPublic

    admin = UserPublic(id=ADMIN_ID, email="admin@test.com", role="admin")
    stream_tables: list[str] = []

    def _table(name: str):
        stream_tables.append(name)
        raise AssertionError(f"complete route must not touch {name}")

    sb = MagicMock()
    sb.table.side_effect = _table

    with (
        patch("app.admin.question_bank.set_intro_stream_uid", return_value="uid-set-only") as set_uid,
        patch("app.admin.stream_videos.complete_stream_video") as complete_skill,
        patch("app.admin.stream_videos.get_supabase", return_value=sb),
        patch("app.storage.stream.set_require_signed_urls"),
        patch(
            "app.storage.stream.get_video",
            return_value={"status": {"state": "ready"}},
        ),
        patch("app.storage.stream.create_signed_playback_token", return_value="tok"),
        patch(
            "app.storage.stream.playback_signed_iframe_url",
            return_value="https://signed.example/iframe",
        ),
        patch("app.admin.stream_videos._customer_code", return_value="customer-test"),
    ):
        out = bank_watch_video_complete_route(
            set_id=SET_ID,
            admin=admin,
            stream_uid="uid-set-only",
            title="Set Watch explainer",
        )

    set_uid.assert_called_once_with(set_id=SET_ID, stream_uid="uid-set-only")
    complete_skill.assert_not_called()
    assert "stream_videos" not in stream_tables
    assert out["intro_stream_uid"] == "uid-set-only"
    assert out["status"] == "ready"


def test_delete_custom_set_clears_assignment_ledger_first():
    deleted: list[tuple[str, str, str]] = []

    def table(name: str):
        m = MagicMock()
        m.delete.return_value = m

        def eq(col, val):
            m._eq = (name, str(col), str(val))
            return m

        def execute():
            deleted.append(m._eq)
            return MagicMock(data=[])

        m.eq.side_effect = eq
        m.execute.side_effect = execute
        return m

    sb = MagicMock()
    sb.table.side_effect = table
    set_row = {
        "id": str(SET_ID),
        "title": "Custom listening",
        "set_number": 3,
        "status": "draft",
        "practice_banks": {"skill": "listening", "bank_number": 5},
    }
    with (
        patch("app.admin.question_bank.get_supabase", return_value=sb),
        patch(
            "app.admin.question_bank._load_set_skill",
            return_value=(set_row, "listening"),
        ),
        patch("app.admin.question_bank._after_question_bank_mutation"),
        patch("app.admin.question_bank.log_admin_action"),
    ):
        res = qb.delete_question_bank_set(set_id=SET_ID, admin_id=ADMIN_ID)

    assert res["ok"] is True
    assert deleted[0] == ("user_practice_assignments", "practice_set_id", str(SET_ID))
    assert deleted[1] == ("practice_sets", "id", str(SET_ID))

