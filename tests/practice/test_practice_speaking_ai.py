"""Practice bank speaking AI helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import UUID

from app.practice.speaking_ai import (
    PRACTICE_SPEAKING_MOCK_TEST_ID,
    SCORE_KIND,
    bootstrap_practice_speaking_attempt,
    build_pending_speaking_score,
    resolve_speaking_part,
)


def test_resolve_speaking_part_from_question_type():
    assert resolve_speaking_part(question_type="speaking_part3") == 3
    assert resolve_speaking_part(question_type="Part 2") == 2
    assert resolve_speaking_part(question_type="p1") == 1


def test_resolve_speaking_part_from_hub_title():
    assert resolve_speaking_part(question_type="", title="SS_P3_02") == 3
    assert resolve_speaking_part(question_type="", title="MT1_ST_P2") == 2
    assert resolve_speaking_part(question_type="", title="speaking-mt1-p1") == 1


def test_resolve_speaking_part_section_fallback():
    assert resolve_speaking_part(question_type="", section_part=2) == 2
    assert resolve_speaking_part(question_type="essay", section_part=9) == 1


def test_build_pending_speaking_score():
    score = build_pending_speaking_score(
        speaking_attempt_id="att-1",
        speaking_manifest_hash="hash-1",
        hub_title="Hub A",
        speaking_review_id="rev-1",
    )
    assert score["kind"] == SCORE_KIND
    assert score["status"] == "pending"
    assert score["speaking_attempt_id"] == "att-1"
    assert score["speaking_manifest_hash"] == "hash-1"
    assert score["speaking_review_id"] == "rev-1"
    assert score["hub_title"] == "Hub A"


def test_bootstrap_abandons_leftover_in_progress_speaking_attempt():
    """Bank hubs share one unique in_progress slot — abandon before insert."""
    user_id = UUID("11111111-1111-4111-8111-111111111111")
    leftover_id = UUID("22222222-2222-4222-8222-222222222222")
    new_id = UUID("33333333-3333-4333-8333-333333333333")
    questions = [
        {
            "id": "44444444-4444-4444-8444-444444444444",
            "question_number": 1,
            "question_type": "speaking_part1",
            "prompt": "Hello",
            "options": {},
        }
    ]
    speaking_repo = MagicMock()
    speaking_repo.find_in_progress_speaking_attempt.return_value = {
        "id": str(leftover_id),
        "status": "in_progress",
    }
    speaking_repo.insert_speaking_attempt.return_value = {
        "id": str(new_id),
        "status": "in_progress",
    }
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[])
    )

    with (
        patch("app.speaking.repository.find_in_progress_speaking_attempt", speaking_repo.find_in_progress_speaking_attempt),
        patch("app.speaking.repository.abandon_speaking_attempt", speaking_repo.abandon_speaking_attempt),
        patch("app.speaking.repository.insert_speaking_attempt", speaking_repo.insert_speaking_attempt),
        patch("app.practice.speaking_ai._sb", return_value=sb),
    ):
        out = bootstrap_practice_speaking_attempt(
            user_id=user_id,
            practice_attempt_id="77777777-7777-4777-8777-777777777777",
            questions=questions,
            section_part=1,
            hub_title="SS_P1_01",
        )

    speaking_repo.find_in_progress_speaking_attempt.assert_called_with(
        user_id=user_id,
        mock_test_id=PRACTICE_SPEAKING_MOCK_TEST_ID,
        part=1,
        mock_attempt_id=None,
    )
    speaking_repo.abandon_speaking_attempt.assert_called_once_with(
        attempt_id=leftover_id
    )
    speaking_repo.insert_speaking_attempt.assert_called_once()
    assert out["speaking_attempt_id"] == str(new_id)
