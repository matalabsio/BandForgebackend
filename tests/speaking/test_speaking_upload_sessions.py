"""Direct-to-R2 Speaking upload-session contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.speaking import service
from app.speaking.schemas import (
    ConfirmSpeakingResponseRequest,
    CreateSpeakingResponseSessionRequest,
)

ATTEMPT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
OTHER_USER_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
MOCK_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
QUESTION_ID = UUID("11111111-1111-4111-8111-111111111111")
RESPONSE_ID = UUID("22222222-2222-4222-8222-222222222222")
IDEMPOTENCY_KEY = "session-idempotency-key-0001"


def _attempt(*, user_id: UUID = USER_ID) -> dict:
    questions, manifest_hash = service._build_manifest(
        [
            {
                "id": str(QUESTION_ID),
                "mock_test_id": str(MOCK_ID),
                "module": "speaking",
                "question_type": "speaking_part1",
                "question_number": 1,
                "part": 1,
                "prompt": "Where are you from?",
                "options": {"max_record_sec": 45},
            }
        ]
    )
    return {
        "id": str(ATTEMPT_ID),
        "user_id": str(user_id),
        "mock_test_id": str(MOCK_ID),
        "module": "speaking",
        "status": "in_progress",
        "part": 1,
        "mock_attempt_id": None,
        "speaking_manifest": service._manifest_payload(questions),
        "speaking_manifest_hash": manifest_hash,
    }


def _request(**changes) -> CreateSpeakingResponseSessionRequest:
    values = {
        "question_id": QUESTION_ID,
        "part": 1,
        "sequence_number": 1,
        "duration_sec": 20,
        "size_bytes": 4000,
        "content_type": "audio/webm",
        "idempotency_key": IDEMPOTENCY_KEY,
    }
    values.update(changes)
    return CreateSpeakingResponseSessionRequest(**values)


def _row(*, status: str = "pending_upload", **changes) -> dict:
    values = {
        "id": str(RESPONSE_ID),
        "attempt_id": str(ATTEMPT_ID),
        "question_id": str(QUESTION_ID),
        "part": 1,
        "sequence_number": 1,
        "audio_url": f"speaking/{ATTEMPT_ID}/responses/response.webm",
        "content_type": "audio/webm",
        "duration_sec": 20,
        "size_bytes": 4000,
        "content_sha256": None,
        "status": status,
        "idempotency_key": IDEMPOTENCY_KEY,
        "upload_expires_at": datetime.now(UTC) + timedelta(minutes=10),
        "confirmed_at": datetime.now(UTC) if status == "confirmed" else None,
        "created_at": datetime.now(UTC),
    }
    values.update(changes)
    return values


def test_create_session_is_idempotent_and_returns_stable_key():
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=_attempt()),
        patch("app.speaking.service.repo.get_speaking_response", return_value=_row()),
        patch(
            "app.speaking.service.generate_presigned_put_url",
            return_value="https://r2.example/upload",
        ),
    ):
        result = service.create_response_session(
            attempt_id=ATTEMPT_ID,
            user_id=USER_ID,
            request=_request(),
        )

    assert result.response_id == RESPONSE_ID
    assert result.idempotency_key == IDEMPOTENCY_KEY
    assert result.idempotent_replay is True


def test_create_session_persists_pending_row_before_signing():
    inserted = _row()
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=_attempt()),
        patch("app.speaking.service.repo.get_speaking_response", return_value=None),
        patch(
            "app.speaking.service.repo.insert_speaking_response_session",
            return_value=inserted,
        ) as insert,
        patch(
            "app.speaking.service.generate_presigned_put_url",
            return_value="https://r2.example/upload",
        ) as sign,
    ):
        result = service.create_response_session(
            attempt_id=ATTEMPT_ID,
            user_id=USER_ID,
            request=_request(),
        )
    assert result.response_id == RESPONSE_ID
    assert result.upload_url == "https://r2.example/upload"
    assert insert.call_args.kwargs["idempotency_key"] == IDEMPOTENCY_KEY
    sign.assert_called_once()


def test_create_session_rejects_owner_and_manifest_mismatches():
    with patch(
        "app.speaking.service.repo.get_attempt",
        return_value=_attempt(user_id=OTHER_USER_ID),
    ):
        with pytest.raises(HTTPException) as owner_error:
            service.create_response_session(
                attempt_id=ATTEMPT_ID,
                user_id=USER_ID,
                request=_request(),
            )
    assert owner_error.value.status_code == 404

    with patch("app.speaking.service.repo.get_attempt", return_value=_attempt()):
        with pytest.raises(HTTPException) as manifest_error:
            service.create_response_session(
                attempt_id=ATTEMPT_ID,
                user_id=USER_ID,
                request=_request(sequence_number=2),
            )
    assert manifest_error.value.status_code == 409


def test_create_session_rejects_duration_and_mime():
    with patch("app.speaking.service.repo.get_attempt", return_value=_attempt()):
        with pytest.raises(HTTPException) as duration_error:
            service.create_response_session(
                attempt_id=ATTEMPT_ID,
                user_id=USER_ID,
                request=_request(duration_sec=46),
            )
        with pytest.raises(HTTPException) as mime_error:
            service.create_response_session(
                attempt_id=ATTEMPT_ID,
                user_id=USER_ID,
                request=_request(content_type="application/octet-stream"),
            )
    assert duration_error.value.status_code == 400
    assert mime_error.value.status_code == 415


def test_confirm_is_idempotent():
    confirmed = _row(status="confirmed")
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=_attempt()),
        patch(
            "app.speaking.service.repo.get_speaking_response_by_id",
            return_value=confirmed,
        ),
        patch(
            "app.speaking.service.repo.queue_speaking_response_transcription",
            return_value=None,
        ),
        patch("app.speaking.service.object_head") as head,
    ):
        result = service.confirm_response(
            attempt_id=ATTEMPT_ID,
            response_id=RESPONSE_ID,
            user_id=USER_ID,
            request=ConfirmSpeakingResponseRequest(
                idempotency_key=IDEMPOTENCY_KEY,
                duration_sec=20,
            ),
        )
    assert result.status == "confirmed"
    assert result.idempotent_replay is True
    head.assert_not_called()


@pytest.mark.parametrize(
    "confirm_request",
    [
        ConfirmSpeakingResponseRequest(
            idempotency_key="different-idempotency-key",
            duration_sec=20,
        ),
        ConfirmSpeakingResponseRequest(
            idempotency_key=IDEMPOTENCY_KEY,
            duration_sec=19,
        ),
    ],
)
def test_confirm_rejects_idempotency_or_duration_mismatch(confirm_request):
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=_attempt()),
        patch(
            "app.speaking.service.repo.get_speaking_response_by_id",
            return_value=_row(),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            service.confirm_response(
                attempt_id=ATTEMPT_ID,
                response_id=RESPONSE_ID,
                user_id=USER_ID,
                request=confirm_request,
            )
    assert exc.value.status_code == 409


@pytest.mark.parametrize(
    ("head", "detail"),
    [
        (None, "Uploaded object was not found."),
        ({"size": 3999, "content_type": "audio/webm"}, "Uploaded object size mismatch."),
        (
            {"size": 4000, "content_type": "audio/mpeg"},
            "Uploaded object content type mismatch.",
        ),
    ],
)
def test_confirm_validates_object_metadata(head, detail):
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=_attempt()),
        patch(
            "app.speaking.service.repo.get_speaking_response_by_id",
            return_value=_row(),
        ),
        patch("app.speaking.service.object_head", return_value=head),
    ):
        with pytest.raises(HTTPException) as exc:
            service.confirm_response(
                attempt_id=ATTEMPT_ID,
                response_id=RESPONSE_ID,
                user_id=USER_ID,
                request=ConfirmSpeakingResponseRequest(
                    idempotency_key=IDEMPOTENCY_KEY,
                    duration_sec=20,
                ),
            )
    assert exc.value.status_code == 409
    assert exc.value.detail == detail


def test_confirm_marks_valid_upload_confirmed():
    confirmed = _row(status="confirmed")
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=_attempt()),
        patch(
            "app.speaking.service.repo.get_speaking_response_by_id",
            return_value=_row(),
        ),
        patch(
            "app.speaking.service.object_head",
            return_value={"size": 4000, "content_type": "audio/webm"},
        ),
        patch(
            "app.speaking.service.repo.confirm_speaking_response",
            return_value=confirmed,
        ) as confirm,
        patch(
            "app.speaking.service.repo.queue_speaking_response_transcription",
            return_value={**confirmed, "transcription_status": "queued"},
        ),
    ):
        result = service.confirm_response(
            attempt_id=ATTEMPT_ID,
            response_id=RESPONSE_ID,
            user_id=USER_ID,
            request=ConfirmSpeakingResponseRequest(
                idempotency_key=IDEMPOTENCY_KEY,
                duration_sec=20,
            ),
        )
    assert result.status == "confirmed"
    confirm.assert_called_once()


def test_confirm_persists_queue_before_scheduling_worker():
    confirmed = _row(status="confirmed")
    queued = {
        **confirmed,
        "transcription_status": "queued",
        "transcription_attempts": 0,
    }
    tasks = BackgroundTasks()
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=_attempt()),
        patch(
            "app.speaking.service.repo.get_speaking_response_by_id",
            return_value=_row(),
        ),
        patch(
            "app.speaking.service.object_head",
            return_value={"size": 4000, "content_type": "audio/webm"},
        ),
        patch(
            "app.speaking.service.repo.confirm_speaking_response",
            return_value=confirmed,
        ),
        patch(
            "app.speaking.service.repo.queue_speaking_response_transcription",
            return_value=queued,
        ) as queue,
    ):
        result = service.confirm_response(
            attempt_id=ATTEMPT_ID,
            response_id=RESPONSE_ID,
            user_id=USER_ID,
            request=ConfirmSpeakingResponseRequest(
                idempotency_key=IDEMPOTENCY_KEY,
                duration_sec=20,
            ),
            background_tasks=tasks,
        )
    queue.assert_called_once()
    assert result.transcription_status == "queued"
    assert len(tasks.tasks) == 1


def test_recovery_exposes_session_uploaded_and_confirmed_states():
    rows = [_row(), _row(id=str(UUID(int=3))), _row(id=str(UUID(int=4)), status="confirmed")]
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=_attempt()),
        patch("app.speaking.service.repo.list_speaking_responses", return_value=rows),
        patch(
            "app.speaking.service.object_head",
            side_effect=[None, {"size": 4000, "content_type": "audio/webm"}],
        ),
    ):
        result = service.list_responses(attempt_id=ATTEMPT_ID, user_id=USER_ID)
    assert [item.status for item in result] == ["session", "uploaded", "confirmed"]


def test_finalize_counts_only_confirmed_responses():
    attempt = _attempt()
    manifest_hash = str(attempt["speaking_manifest_hash"])
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=attempt),
        patch(
            "app.speaking.service.repo.get_speaking_review_for_attempt",
            return_value=None,
        ),
        patch(
            "app.speaking.service.repo.list_speaking_responses",
            return_value=[_row(status="pending_upload")],
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            service.finalize_attempt(
                attempt_id=ATTEMPT_ID,
                user_id=USER_ID,
                manifest_hash=manifest_hash,
            )
    assert exc.value.status_code == 409
    assert exc.value.detail["received_response_count"] == 0
