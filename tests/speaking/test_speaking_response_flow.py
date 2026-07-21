"""Durable Speaking response and finalization service tests."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.speaking import service

ATTEMPT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
MOCK_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
QUESTION_1 = UUID("11111111-1111-4111-8111-111111111111")
QUESTION_2 = UUID("22222222-2222-4222-8222-222222222222")
RESPONSE_1 = UUID("33333333-3333-4333-8333-333333333333")
RESPONSE_2 = UUID("44444444-4444-4444-8444-444444444444")
REVIEW_ID = UUID("55555555-5555-4555-8555-555555555555")


def _question_rows() -> list[dict]:
    return [
        {
            "id": str(QUESTION_1),
            "mock_test_id": str(MOCK_ID),
            "module": "speaking",
            "question_type": "speaking_part1",
            "question_number": 1,
            "part": 1,
            "prompt": "Where are you from?",
            "options": {"duration_hint_sec": 30, "part_label": "Part 1"},
        },
        {
            "id": str(QUESTION_2),
            "mock_test_id": str(MOCK_ID),
            "module": "speaking",
            "question_type": "speaking_part2",
            "question_number": 1,
            "part": 2,
            "prompt": "Describe a skill you learned.",
            "options": {"duration_hint_sec": 120, "part_label": "Part 2"},
        },
    ]


def _attempt(*, status: str = "in_progress") -> tuple[dict, str]:
    questions, manifest_hash = service._build_manifest(_question_rows())
    return (
        {
            "id": str(ATTEMPT_ID),
            "user_id": str(USER_ID),
            "mock_test_id": str(MOCK_ID),
            "module": "speaking",
            "status": status,
            "part": 1,
            "mock_attempt_id": None,
            "speaking_manifest": service._manifest_payload(questions),
            "speaking_manifest_hash": manifest_hash,
        },
        manifest_hash,
    )


def _response_row(
    *,
    response_id: UUID,
    question_id: UUID,
    sequence_number: int,
    part: int,
    content_sha256: str,
) -> dict:
    return {
        "id": str(response_id),
        "attempt_id": str(ATTEMPT_ID),
        "question_id": str(question_id),
        "part": part,
        "sequence_number": sequence_number,
        "audio_url": f"speaking/{ATTEMPT_ID}/responses/{sequence_number}.webm",
        "content_type": "audio/webm",
        "duration_sec": 10,
        "size_bytes": 2500,
        "content_sha256": content_sha256,
        "status": "confirmed",
        "created_at": datetime.now(UTC),
    }


def test_upload_response_is_idempotent_for_same_content():
    attempt, _ = _attempt()
    audio = b"a" * 2500
    digest = service.hashlib.sha256(audio).hexdigest()
    existing = _response_row(
        response_id=RESPONSE_1,
        question_id=QUESTION_1,
        sequence_number=1,
        part=1,
        content_sha256=digest,
    )
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=attempt),
        patch(
            "app.speaking.service.repo.get_speaking_response",
            return_value=existing,
        ),
        patch(
            "app.speaking.service.repo.queue_speaking_response_transcription",
            return_value=None,
        ),
        patch("app.speaking.service.upload_object") as upload,
    ):
        result = service.upload_response(
            attempt_id=ATTEMPT_ID,
            user_id=USER_ID,
            question_id=QUESTION_1,
            part=1,
            sequence_number=1,
            duration_sec=10,
            audio_bytes=audio,
            content_type="audio/webm",
        )

    assert result.idempotent_replay is True
    upload.assert_not_called()


def test_upload_response_recovers_pending_direct_upload_session():
    attempt, _ = _attempt()
    audio = b"a" * 2500
    pending = {
        **_response_row(
            response_id=RESPONSE_1,
            question_id=QUESTION_1,
            sequence_number=1,
            part=1,
            content_sha256="",
        ),
        "status": "pending_upload",
        "idempotency_key": "upload-session-key",
    }
    confirmed = {**pending, "status": "confirmed"}

    with (
        patch("app.speaking.service.repo.get_attempt", return_value=attempt),
        patch(
            "app.speaking.service.repo.get_speaking_response",
            return_value=pending,
        ),
        patch(
            "app.speaking.service.repo.confirm_speaking_response",
            return_value=confirmed,
        ) as confirm,
        patch(
            "app.speaking.service.repo.queue_speaking_response_transcription",
            return_value=None,
        ),
        patch("app.speaking.service.upload_object") as upload,
    ):
        result = service.upload_response(
            attempt_id=ATTEMPT_ID,
            user_id=USER_ID,
            question_id=QUESTION_1,
            part=1,
            sequence_number=1,
            duration_sec=10,
            audio_bytes=audio,
            content_type="audio/webm",
        )

    assert result.status == "confirmed"
    assert result.idempotent_replay is True
    upload.assert_called_once_with(
        key=pending["audio_url"],
        body=audio,
        content_type="audio/webm",
    )
    confirm.assert_called_once()


def test_upload_response_rejects_manifest_metadata_mismatch():
    attempt, _ = _attempt()
    with patch("app.speaking.service.repo.get_attempt", return_value=attempt):
        with pytest.raises(HTTPException) as exc:
            service.upload_response(
                attempt_id=ATTEMPT_ID,
                user_id=USER_ID,
                question_id=QUESTION_1,
                part=3,
                sequence_number=1,
                duration_sec=10,
                audio_bytes=b"a" * 2500,
                content_type="audio/webm",
            )
    assert exc.value.status_code == 409


def test_finalize_requires_every_manifest_response():
    attempt, manifest_hash = _attempt()
    first = _response_row(
        response_id=RESPONSE_1,
        question_id=QUESTION_1,
        sequence_number=1,
        part=1,
        content_sha256="a" * 64,
    )
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=attempt),
        patch(
            "app.speaking.service.repo.get_speaking_review_for_attempt",
            return_value=None,
        ),
        patch(
            "app.speaking.service.repo.list_speaking_responses",
            return_value=[first],
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            service.finalize_attempt(
                attempt_id=ATTEMPT_ID,
                user_id=USER_ID,
                manifest_hash=manifest_hash,
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["missing_question_ids"] == [str(QUESTION_2)]


def test_finalize_creates_one_review_for_complete_response_set():
    attempt, manifest_hash = _attempt()
    responses = [
        _response_row(
            response_id=RESPONSE_1,
            question_id=QUESTION_1,
            sequence_number=1,
            part=1,
            content_sha256="a" * 64,
        ),
        _response_row(
            response_id=RESPONSE_2,
            question_id=QUESTION_2,
            sequence_number=2,
            part=2,
            content_sha256="b" * 64,
        ),
    ]
    review = {"id": str(REVIEW_ID)}
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=attempt),
        patch(
            "app.speaking.service.repo.get_speaking_review_for_attempt",
            return_value=None,
        ),
        patch(
            "app.speaking.service.repo.list_speaking_responses",
            return_value=responses,
        ),
        patch(
            "app.speaking.service.repo.insert_speaking_review",
            return_value=review,
        ) as insert_review,
        patch(
            "app.speaking.service.repo.update_speaking_review_evaluation"
        ) as update_review,
        patch(
            "app.speaking.service.repo.mark_attempt_completed",
            return_value={**attempt, "status": "completed"},
        ),
    ):
        result = service.finalize_attempt(
            attempt_id=ATTEMPT_ID,
            user_id=USER_ID,
            manifest_hash=manifest_hash,
            student_name="Student",
        )

    assert result.status == "completed"
    assert result.review_id == REVIEW_ID
    meta = insert_review.call_args.kwargs["submission_meta"]
    assert meta["response_count"] == 2
    assert [item["question_id"] for item in meta["responses"]] == [
        str(QUESTION_1),
        str(QUESTION_2),
    ]
    update_review.assert_called_once()


def test_start_enforces_mock_unlock_and_returns_frozen_manifest():
    with (
        patch("app.speaking.service.repo.get_mock_test") as get_mock,
        patch(
            "app.speaking.service.repo.list_speaking_questions",
            return_value=_question_rows(),
        ),
        patch(
            "app.speaking.service.repo.find_in_progress_speaking_attempt",
            return_value=None,
        ),
        patch("app.speaking.service.repo.insert_speaking_attempt") as insert,
        patch(
            "app.services.mock_orchestrator.assert_module_unlocked"
        ) as assert_unlocked,
    ):
        get_mock.return_value = {
            "id": str(MOCK_ID),
            "title": "Mock",
            "description": None,
        }
        insert.return_value = {
            "id": str(ATTEMPT_ID),
            "started_at": datetime.now(UTC),
            "status": "in_progress",
        }
        result = service.start_attempt(
            mock_test_id=MOCK_ID,
            user_id=USER_ID,
            mock_attempt_id=UUID("66666666-6666-4666-8666-666666666666"),
        )

    assert_unlocked.assert_called_once()
    assert result.expected_response_count == 2
    assert [question.sequence_number for question in result.questions] == [1, 2]
    assert result.questions[0].prep_seconds == 0
    assert result.questions[0].max_recording_seconds == 45
    assert result.questions[1].prep_seconds == 60
    assert result.questions[1].max_recording_seconds == 120
    assert result.manifest_hash
