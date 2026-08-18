"""Phase 1: practice catalog version + rewrite fingerprint freshness."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.admin import question_bank as qb
from app.admin.schemas import (
    ListeningBuilderQuestionIn,
    ListeningBuilderSaveRequest,
    PatchQuestionBankSetStatusRequest,
)
from app.cache.hybrid_cache import get_json, set_json
from app.learning.service import _progress_fingerprint
from app.practice import repository

SET_ID = UUID("11111111-1111-4111-8111-111111111111")
ADMIN_ID = UUID("22222222-2222-4222-8222-222222222222")


def _listening_body() -> ListeningBuilderSaveRequest:
    return ListeningBuilderSaveRequest(
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


def _set_row(*, status: str) -> dict:
    return {
        "id": str(SET_ID),
        "status": status,
        "practice_banks": {"skill": "listening", "bank_number": 5},
    }


def test_student_visible_status_change_only_when_published_enters_or_leaves():
    assert qb._student_visible_status_change("draft", "published") is True
    assert qb._student_visible_status_change("published", "draft") is True
    assert qb._student_visible_status_change("published", "archived") is True
    assert qb._student_visible_status_change("archived", "published") is True
    assert qb._student_visible_status_change("draft", "archived") is False
    assert qb._student_visible_status_change("draft", "draft") is False
    assert qb._student_visible_status_change("published", "published") is False


def test_publish_bumps_catalog_version():
    sb = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.update.return_value = chain
    chain.execute.return_value = MagicMock(data=[_set_row(status="draft")])
    sb.table.return_value = chain

    with (
        patch("app.admin.question_bank.get_supabase", return_value=sb),
        patch("app.admin.question_bank.bank_publish_blockers", return_value=[]),
        patch("app.admin.question_bank.refresh_hub_submit_configs"),
        patch("app.admin.question_bank.log_admin_action"),
        patch(
            "app.practice.repository.bump_practice_catalog_version",
            return_value=3,
        ) as bump,
        patch("app.admin.question_bank._clear_practice_catalog_cache") as clear,
    ):
        qb.patch_question_bank_set_status(
            set_id=SET_ID,
            body=PatchQuestionBankSetStatusRequest(status="published"),
            admin_id=ADMIN_ID,
        )
    bump.assert_not_called()
    clear.assert_called_once()
    sb.rpc.assert_called_once_with(
        "apply_practice_set_status",
        {"p_set_id": str(SET_ID), "p_status": "published"},
    )


def test_blocked_publish_does_not_bump_catalog_version():
    sb = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(data=[_set_row(status="draft")])
    sb.table.return_value = chain

    with (
        patch("app.admin.question_bank.get_supabase", return_value=sb),
        patch(
            "app.admin.question_bank.bank_publish_blockers",
            return_value=["Listening: add at least one question before publishing."],
        ),
        patch(
            "app.practice.repository.bump_practice_catalog_version",
        ) as bump,
        patch("app.admin.question_bank._clear_practice_catalog_cache") as clear,
    ):
        with pytest.raises(HTTPException) as exc:
            qb.patch_question_bank_set_status(
                set_id=SET_ID,
                body=PatchQuestionBankSetStatusRequest(status="published"),
                admin_id=ADMIN_ID,
            )
    assert exc.value.status_code == 400
    bump.assert_not_called()
    clear.assert_not_called()


def test_unpublish_bumps_catalog_version():
    sb = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.update.return_value = chain
    chain.execute.return_value = MagicMock(data=[_set_row(status="published")])
    sb.table.return_value = chain

    with (
        patch("app.admin.question_bank.get_supabase", return_value=sb),
        patch("app.admin.question_bank.refresh_hub_submit_configs"),
        patch("app.admin.question_bank.log_admin_action"),
        patch(
            "app.practice.repository.bump_practice_catalog_version",
            return_value=4,
        ) as bump,
        patch("app.admin.question_bank._clear_practice_catalog_cache") as clear,
    ):
        qb.patch_question_bank_set_status(
            set_id=SET_ID,
            body=PatchQuestionBankSetStatusRequest(status="archived"),
            admin_id=ADMIN_ID,
        )
    bump.assert_not_called()
    clear.assert_called_once()
    sb.rpc.assert_called_once_with(
        "apply_practice_set_status",
        {"p_set_id": str(SET_ID), "p_status": "archived"},
    )


def test_draft_save_does_not_bump_catalog_version():
    with (
        patch(
            "app.admin.question_bank._load_set_skill",
            return_value=(_set_row(status="draft"), "listening"),
        ),
        patch("app.admin.question_bank._upsert_section", return_value="sec-1"),
        patch("app.admin.question_bank._replace_questions"),
        patch("app.admin.question_bank.refresh_hub_submit_configs"),
        patch("app.admin.question_bank.log_admin_action"),
        patch("app.admin.question_bank.get_supabase", return_value=MagicMock()),
        patch(
            "app.practice.repository.bump_practice_catalog_version",
        ) as bump,
        patch("app.admin.question_bank._clear_practice_catalog_cache") as clear,
    ):
        res = qb.save_bank_listening(
            set_id=SET_ID, part=1, body=_listening_body(), admin_id=ADMIN_ID
        )
    assert res.ok is True
    bump.assert_not_called()
    clear.assert_called_once()


def test_published_save_bumps_catalog_version():
    with (
        patch(
            "app.admin.question_bank._load_set_skill",
            return_value=(_set_row(status="published"), "listening"),
        ),
        patch("app.admin.question_bank._upsert_section", return_value="sec-1"),
        patch("app.admin.question_bank._replace_questions"),
        patch("app.admin.question_bank.refresh_hub_submit_configs"),
        patch("app.admin.question_bank.log_admin_action"),
        patch("app.admin.question_bank.get_supabase", return_value=MagicMock()),
        patch(
            "app.practice.repository.bump_practice_catalog_version",
            return_value=5,
        ) as bump,
        patch("app.admin.question_bank._clear_practice_catalog_cache") as clear,
    ):
        res = qb.save_bank_listening(
            set_id=SET_ID, part=1, body=_listening_body(), admin_id=ADMIN_ID
        )
    assert res.ok is True
    bump.assert_called_once()
    clear.assert_called_once()


def test_rewrite_fingerprint_changes_when_only_catalog_version_changes():
    progress = {"h1": {"status": "completed"}}
    weak = {"listening": ["map"]}
    a = _progress_fingerprint(progress, weak_tags_by_skill=weak, catalog_version=1)
    b = _progress_fingerprint(progress, weak_tags_by_skill=weak, catalog_version=2)
    c = _progress_fingerprint(progress, weak_tags_by_skill=weak, catalog_version=1)
    assert a != b
    assert a == c
    same_progress_no_weak = _progress_fingerprint(progress, catalog_version=1)
    assert same_progress_no_weak != a


def test_clear_hub_list_cache_drops_assignable_grouped_without_ttl_wait():
    stale = {
        "listening": [{"id": "old"}],
        "reading": [],
        "writing": [],
        "speaking": [],
    }
    fresh_row = {
        "id": "new-hub",
        "slug": "listening-custom-new",
        "set_id": "set-new",
        "sort_order": 1,
        "practice_prompt": "",
        "submit_config": {},
        "practice_sets": {
            "id": "set-new",
            "set_number": 5,
            "title": "S5",
            "status": "published",
            "difficulty": "medium",
            "practice_banks": {
                "skill": "listening",
                "bank_number": 5,
                "title": "Custom",
            },
        },
    }
    set_json("practice:hubs:assignable_grouped", stale, 60)
    assert get_json("practice:hubs:assignable_grouped")["listening"][0]["id"] == "old"

    cached = repository.list_assignable_hubs_grouped()
    assert cached["listening"][0]["id"] == "old"

    repository.clear_hub_list_cache()
    assert get_json("practice:hubs:assignable_grouped") is None

    with (
        patch(
            "app.practice.repository._execute_hub_query",
            return_value=MagicMock(data=[fresh_row]),
        ),
        patch(
            "app.practice.repository._filter_assignable_hub_rows",
            side_effect=lambda rows: rows,
        ),
        patch("app.practice.repository.get_supabase", return_value=MagicMock()),
    ):
        grouped = repository.list_assignable_hubs_grouped()
    assert grouped["listening"][0]["id"] == "new-hub"


def test_bump_practice_catalog_version_uses_postgres_rpc():
    sb = MagicMock()
    with (
        patch("app.practice.repository.get_supabase", return_value=sb),
        patch("app.practice.repository._exec", return_value=MagicMock(data=7)) as exec_fn,
    ):
        assert repository.bump_practice_catalog_version() == 7
    sb.rpc.assert_called_once_with("bump_practice_catalog_version")
    exec_fn.assert_called_once()


def test_apply_practice_set_status_sql_bumps_version_in_same_transaction():
    sql = (
        Path(__file__).resolve().parents[2]
        / "supabase"
        / "migrations"
        / "20260818123000_practice_publish_bumps_catalog_version.sql"
    ).read_text()
    assert "bump_practice_catalog_version()" in sql
    assert "enqueue_practice_catalog_changed" in sql
    assert "catalog_version" in sql


def test_catalog_version_bump_failure_is_retried_then_raised():
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise RuntimeError("bump down")

    with patch(
        "app.practice.repository.bump_practice_catalog_version",
        side_effect=boom,
    ):
        with pytest.raises(RuntimeError, match="bump down"):
            qb._bump_catalog_version_strict(attempts=3)
    assert calls["n"] == 3


def test_catalog_version_bump_recovers_after_transient_failure():
    with patch(
        "app.practice.repository.bump_practice_catalog_version",
        side_effect=[RuntimeError("once"), RuntimeError("twice"), 9],
    ):
        assert qb._bump_catalog_version_strict(attempts=3) == 9


def test_published_save_still_bumps_via_python_and_does_not_swallow():
    with (
        patch(
            "app.admin.question_bank._load_set_skill",
            return_value=(_set_row(status="published"), "listening"),
        ),
        patch("app.admin.question_bank._upsert_section", return_value="sec-1"),
        patch("app.admin.question_bank._replace_questions"),
        patch("app.admin.question_bank.refresh_hub_submit_configs"),
        patch("app.admin.question_bank.log_admin_action"),
        patch("app.admin.question_bank.get_supabase", return_value=MagicMock()),
        patch(
            "app.practice.repository.bump_practice_catalog_version",
            side_effect=RuntimeError("permanent"),
        ),
        patch("app.admin.question_bank._clear_practice_catalog_cache") as clear,
    ):
        with pytest.raises(RuntimeError, match="permanent"):
            qb.save_bank_listening(
                set_id=SET_ID, part=1, body=_listening_body(), admin_id=ADMIN_ID
            )
    clear.assert_not_called()
