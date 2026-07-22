"""Business logic for the Speaking module."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, HTTPException, status

from app.config import get_settings
from app.schemas.test_engine import TestSummary
from app.services.mock_progress_timing import MockProgressTiming
from app.speaking import repository as repo
from app.speaking.constants import (
    SPEAKING_DURATION_MINUTES,
    SPEAKING_PART1_MAX_RECORDING_SECONDS,
    SPEAKING_PART1_RECORD_SECONDS,
    SPEAKING_PART2_MAX_RECORDING_SECONDS,
    SPEAKING_PART3_MAX_RECORDING_SECONDS,
)
from app.speaking.schemas import (
    ConfirmSpeakingResponseRequest,
    CreateSpeakingResponseSessionRequest,
    SpeakingFluencyMetrics,
    SpeakingBiggestGap,
    SpeakingCriterionResult,
    SpeakingEligibilityResponse,
    SpeakingEvidenceSpan,
    SpeakingPatternExample,
    SpeakingPronunciationAdvisory,
    SpeakingReportAnalysis,
    SpeakingReportAttempt,
    SpeakingReportEvidence,
    SpeakingReportFluency,
    SpeakingReportPart,
    SpeakingReportPattern,
    SpeakingReportRelease,
    SpeakingReportResponseItem,
    SpeakingReportScores,
    SpeakingReportStudent,
    SpeakingReportSummary,
    SpeakingResponsePause,
    SpeakingResponseMetrics,
    SpeakingResponsePublic,
    SpeakingResponseSession,
    SpeakingHumanCriteria,
    SpeakingPauseMarker,
    SpeakingPendingResponse,
    SpeakingPendingTranscriptResponse,
    SpeakingQuestionPublic,
    SpeakingReleaseMetadata,
    SpeakingReportResponse,
    SpeakingReviewerPublic,
    SpeakingTranscriptWord,
    StartSpeakingResponse,
    SubmitSpeakingResponse,
)
from app.speaking.evaluation_schemas import SpeakingEvaluation
from app.speaking.fluency_metrics import aggregate_fluency_metrics, long_pause_markers
from app.speaking.response_transcriber import (
    reconcile_attempt_transcriptions,
    transcribe_response,
)
from app.storage.r2 import (
    generate_presigned_put_url,
    generate_signed_url,
    object_head,
    upload_object,
)
from app.speaking.ai_evaluator import run_speaking_evaluation

SPEAKING_UPLOAD_EXPIRY_SECONDS = 15 * 60
SPEAKING_MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def _default_max_recording_seconds(part: int) -> int:
    if part == 2:
        return SPEAKING_PART2_MAX_RECORDING_SECONDS
    if part == 3:
        return SPEAKING_PART3_MAX_RECORDING_SECONDS
    return SPEAKING_PART1_MAX_RECORDING_SECONDS


SPEAKING_AUDIO_CONTENT_TYPES = {
    "audio/webm",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "audio/ogg",
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
}
SPEAKING_PART_LABELS = {
    1: "Introduction and Interview",
    2: "Long Turn",
    3: "Discussion",
}


def _is_dev() -> bool:
    return get_settings().app_env.strip().lower() == "development"


def _audio_extension_for_upload(
    content_type: str | None,
    filename: str | None = None,
) -> str:
    """Derive a safe R2 key extension from MIME type or uploaded filename."""
    raw = (content_type or "").lower().split(";", 1)[0].strip()
    if "mp4" in raw or raw in {"audio/m4a", "audio/x-m4a"}:
        return "mp4"
    if "ogg" in raw:
        return "ogg"
    if "mpeg" in raw or raw == "audio/mp3":
        return "mp3"
    if "wav" in raw:
        return "wav"
    if "webm" in raw:
        return "webm"

    name = (filename or "").lower().rsplit(".", 1)
    if len(name) == 2:
        ext = name[1]
        if ext in {"webm", "mp4", "m4a", "ogg", "mp3", "wav"}:
            return "mp4" if ext == "m4a" else ext

    return "webm"


def _round_half(value: float) -> float:
    return round(value * 2) / 2


def _duration_band_estimate(
    *, duration_sec: int | None, hint_sec: int | None
) -> float | None:
    if not duration_sec or duration_sec <= 0:
        return None
    target = hint_sec or 60
    ratio = min(1.0, duration_sec / target)
    return _round_half(5.0 + ratio * 1.5)


def _ensure_owner(attempt: dict[str, Any], user_id: UUID) -> None:
    from app.security.ownership import ensure_owner_or_not_found

    ensure_owner_or_not_found(attempt, user_id)


def _parse_started_at(attempt: dict[str, Any]) -> datetime:
    raw = attempt.get("started_at")
    if isinstance(raw, str):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if isinstance(raw, datetime):
        return raw
    return datetime.now(UTC)


def _row_to_question(row: dict[str, Any]) -> SpeakingQuestionPublic:
    opts = row.get("options") if isinstance(row.get("options"), dict) else {}
    part = int(row.get("part") or 1)
    prep_seconds = int(
        opts.get("prep_seconds")
        or opts.get("prep_sec")
        or (60 if part == 2 else 0)
    )
    max_recording_seconds = int(
        opts.get("max_recording_seconds")
        or opts.get("max_record_sec")
        or opts.get("record_sec")
        or _default_max_recording_seconds(part)
    )
    # Part 1: allow full testing window even if catalog still has a short cap.
    if part == 1:
        max_recording_seconds = max(
            max_recording_seconds, SPEAKING_PART1_MAX_RECORDING_SECONDS
        )
    return SpeakingQuestionPublic(
        id=UUID(str(row["id"])),
        question_number=int(row.get("question_number") or 1),
        question_type=str(row.get("question_type") or "speaking_part1"),
        prompt=str(row.get("prompt") or ""),
        part=part,
        sequence_number=int(row.get("sequence_number") or 1),
        kind=str(opts.get("kind") or "question"),
        prep_sec=prep_seconds,
        record_sec=_parse_optional_int(opts.get("record_sec")),
        max_record_sec=max_recording_seconds,
        prep_seconds=prep_seconds,
        max_recording_seconds=max_recording_seconds,
        duration_hint_sec=int(
            opts.get("duration_hint_sec")
            or opts.get("record_sec")
            or opts.get("max_record_sec")
            or SPEAKING_PART1_RECORD_SECONDS
        ),
        part_label=str(opts.get("part_label") or "Part 1"),
    )


def _build_manifest(rows: list[dict[str, Any]]) -> tuple[list[SpeakingQuestionPublic], str]:
    ordered = sorted(
        rows,
        key=lambda row: (
            int(row.get("part") or 1),
            int(row.get("question_number") or 1),
            str(row.get("id")),
        ),
    )
    questions: list[SpeakingQuestionPublic] = []
    for sequence_number, row in enumerate(ordered, start=1):
        questions.append(
            _row_to_question({**row, "sequence_number": sequence_number})
        )
    canonical = [
        question.model_dump(mode="json", exclude_none=False) for question in questions
    ]
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return questions, digest


def _manifest_payload(
    questions: list[SpeakingQuestionPublic],
) -> list[dict[str, Any]]:
    return [question.model_dump(mode="json", exclude_none=False) for question in questions]


def _attempt_manifest(
    attempt: dict[str, Any],
) -> tuple[list[SpeakingQuestionPublic], str]:
    raw = attempt.get("speaking_manifest")
    stored_hash = attempt.get("speaking_manifest_hash")
    if isinstance(raw, list) and raw:
        questions = []
        for item in raw:
            normalized = dict(item)
            part = int(normalized.get("part") or 1)
            max_seconds = int(
                normalized.get("max_recording_seconds")
                or normalized.get("max_record_sec")
                or normalized.get("record_sec")
                or _default_max_recording_seconds(part)
            )
            if part == 1:
                max_seconds = max(max_seconds, SPEAKING_PART1_MAX_RECORDING_SECONDS)
            normalized.setdefault(
                "prep_seconds",
                normalized.get("prep_sec") or (60 if part == 2 else 0),
            )
            normalized.setdefault("max_recording_seconds", max_seconds)
            questions.append(SpeakingQuestionPublic.model_validate(normalized))
        canonical_hash = hashlib.sha256(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if stored_hash and str(stored_hash) != canonical_hash:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Speaking question manifest is invalid.",
            )
        return questions, canonical_hash

    rows = repo.list_speaking_questions(
        mock_test_id=UUID(str(attempt["mock_test_id"]))
    )
    if not rows:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="No speaking questions configured for this mock.",
        )
    questions, manifest_hash = _build_manifest(rows)
    repo.update_attempt_manifest(
        attempt_id=UUID(str(attempt["id"])),
        manifest=_manifest_payload(questions),
        manifest_hash=manifest_hash,
    )
    return questions, manifest_hash


def get_eligibility(
    *,
    mock_test_id: UUID,
    user_id: UUID,
    mock_attempt_id: UUID | None,
) -> SpeakingEligibilityResponse:
    if mock_attempt_id is None:
        return SpeakingEligibilityResponse(
            eligible=True,
            mock_test_id=mock_test_id,
        )
    from app.services.mock_orchestrator import assert_module_unlocked

    try:
        assert_module_unlocked(
            mock_attempt_id=mock_attempt_id,
            user_id=user_id,
            mock_test_id=mock_test_id,
            module="speaking",
            part=1,
        )
    except HTTPException as exc:
        if exc.status_code != status.HTTP_403_FORBIDDEN:
            raise
        reason = (
            str(exc.detail.get("message") or exc.detail)
            if isinstance(exc.detail, dict)
            else str(exc.detail)
        )
        return SpeakingEligibilityResponse(
            eligible=False,
            reason=reason,
            mock_test_id=mock_test_id,
            mock_attempt_id=mock_attempt_id,
        )
    return SpeakingEligibilityResponse(
        eligible=True,
        mock_test_id=mock_test_id,
        mock_attempt_id=mock_attempt_id,
    )


def start_attempt(
    *,
    mock_test_id: UUID,
    user_id: UUID,
    part: int = 1,
    force_new: bool = False,
    mock_attempt_id: UUID | None = None,
    student_name: str | None = None,
) -> StartSpeakingResponse:
    if part != 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Only Part 1 is available.")

    if mock_attempt_id is not None:
        from app.services.mock_orchestrator import assert_module_unlocked

        assert_module_unlocked(
            mock_attempt_id=mock_attempt_id,
            user_id=user_id,
            mock_test_id=mock_test_id,
            module="speaking",
            part=part,
        )

    test_row = repo.get_mock_test(mock_test_id, allow_unpublished=_is_dev())
    rows = repo.list_speaking_questions(mock_test_id=mock_test_id)
    if not rows:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="No speaking question configured for this mock.",
        )
    questions, current_manifest_hash = _build_manifest(rows)

    existing = repo.find_in_progress_speaking_attempt(
        user_id=user_id,
        mock_test_id=mock_test_id,
        part=part,
        mock_attempt_id=mock_attempt_id,
    )
    if existing and force_new:
        repo.abandon_speaking_attempt(attempt_id=UUID(str(existing["id"])))
        existing = None

    test = TestSummary(
        id=UUID(str(test_row["id"])),
        title=str(test_row["title"]),
        description=test_row.get("description"),
    )

    if existing:
        existing_attempt = repo.get_attempt(UUID(str(existing["id"])))
        frozen_questions, manifest_hash = _attempt_manifest(existing_attempt)
        return StartSpeakingResponse(
            attempt_id=UUID(str(existing["id"])),
            started_at=_parse_started_at(existing),
            server_time=datetime.now(UTC),
            status=str(existing.get("status", "in_progress")),
            part=part,
            duration_seconds=SPEAKING_DURATION_MINUTES * 60,
            resumed=True,
            test=test,
            question=frozen_questions[0],
            questions=frozen_questions,
            manifest_hash=manifest_hash,
            expected_response_count=len(frozen_questions),
            student_name=student_name,
        )

    try:
        row = repo.insert_speaking_attempt(
            user_id=user_id,
            mock_test_id=mock_test_id,
            mock_attempt_id=mock_attempt_id,
            part=part,
            speaking_manifest=_manifest_payload(questions),
            speaking_manifest_hash=current_manifest_hash,
        )
    except Exception:
        raced = repo.find_in_progress_speaking_attempt(
            user_id=user_id,
            mock_test_id=mock_test_id,
            part=part,
            mock_attempt_id=mock_attempt_id,
        )
        if raced is None:
            raise
        row = raced
        frozen_attempt = repo.get_attempt(UUID(str(row["id"])))
        questions, current_manifest_hash = _attempt_manifest(frozen_attempt)
        resumed = True
    else:
        resumed = False
    return StartSpeakingResponse(
        attempt_id=UUID(str(row["id"])),
        started_at=_parse_started_at(row),
        server_time=datetime.now(UTC),
        status=str(row.get("status", "in_progress")),
        part=part,
        duration_seconds=SPEAKING_DURATION_MINUTES * 60,
        resumed=resumed,
        test=test,
        question=questions[0],
        questions=questions,
        manifest_hash=current_manifest_hash,
        expected_response_count=len(questions),
        student_name=student_name,
    )


def _response_to_public(
    row: dict[str, Any],
    *,
    idempotent_replay: bool = False,
    recovery_status: str | None = None,
) -> SpeakingResponsePublic:
    return SpeakingResponsePublic(
        id=UUID(str(row["id"])),
        attempt_id=UUID(str(row["attempt_id"])),
        question_id=UUID(str(row["question_id"])),
        part=int(row["part"]),
        sequence_number=int(row["sequence_number"]),
        duration_sec=(int(row["duration_sec"]) if row.get("duration_sec") is not None else None),
        size_bytes=(int(row["size_bytes"]) if row.get("size_bytes") is not None else None),
        content_type=str(row["content_type"]),
        status=recovery_status or str(row.get("status") or "confirmed"),
        created_at=row["created_at"],
        confirmed_at=row.get("confirmed_at"),
        expires_at=row.get("upload_expires_at"),
        idempotency_key=(
            str(row["idempotency_key"]) if row.get("idempotency_key") else None
        ),
        idempotent_replay=idempotent_replay,
        transcription_status=str(
            row.get("transcription_status") or "not_queued"
        ),
        transcription_attempts=int(row.get("transcription_attempts") or 0),
        transcription_error=(
            str(row["transcription_error"])
            if row.get("transcription_error")
            else None
        ),
    )


def _normalized_audio_content_type(content_type: str) -> str:
    normalized = content_type.lower().split(";", 1)[0].strip()
    if normalized not in SPEAKING_AUDIO_CONTENT_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported Speaking audio content type.",
        )
    return normalized


def _manifest_question(
    attempt: dict[str, Any],
    *,
    question_id: UUID,
    part: int,
    sequence_number: int,
) -> SpeakingQuestionPublic:
    questions, _ = _attempt_manifest(attempt)
    expected = next((question for question in questions if question.id == question_id), None)
    if expected is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Question is not part of this attempt's Speaking manifest.",
        )
    if expected.part != part or expected.sequence_number != sequence_number:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": "Response metadata does not match the Speaking manifest.",
                "expected_part": expected.part,
                "expected_sequence_number": expected.sequence_number,
            },
        )
    return expected


def create_response_session(
    *,
    attempt_id: UUID,
    user_id: UUID,
    request: CreateSpeakingResponseSessionRequest,
) -> SpeakingResponseSession:
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "speaking":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not a speaking attempt.")
    if attempt.get("status") != "in_progress":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Attempt cannot accept responses (status={attempt.get('status')}).",
        )

    question = _manifest_question(
        attempt,
        question_id=request.question_id,
        part=request.part,
        sequence_number=request.sequence_number,
    )
    if request.duration_sec > question.max_recording_seconds:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Recording duration exceeds the server limit.",
                "max_recording_seconds": question.max_recording_seconds,
            },
        )
    if request.size_bytes > SPEAKING_MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Recording is too large.")
    content_type = _normalized_audio_content_type(request.content_type)

    existing = repo.get_speaking_response(
        attempt_id=attempt_id,
        question_id=request.question_id,
    )
    if existing:
        expected_key = str(existing.get("idempotency_key") or "")
        if not expected_key:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="A response is already stored through the compatibility upload.",
            )
        supplied_key = request.idempotency_key
        metadata_matches = (
            int(existing["part"]) == request.part
            and int(existing["sequence_number"]) == request.sequence_number
            and int(existing["duration_sec"]) == request.duration_sec
            and int(existing["size_bytes"]) == request.size_bytes
            and str(existing["content_type"]) == content_type
        )
        if not metadata_matches or (supplied_key and supplied_key != expected_key):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="A different upload session already exists for this question.",
            )
        if str(existing.get("status")) == "confirmed":
            return SpeakingResponseSession(
                response_id=UUID(str(existing["id"])),
                upload_url="",
                expires_at=existing.get("upload_expires_at") or datetime.now(UTC),
                idempotency_key=expected_key,
                idempotent_replay=True,
            )
        expires_at = existing.get("upload_expires_at")
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if not isinstance(expires_at, datetime) or expires_at <= datetime.now(UTC):
            expires_at = datetime.now(UTC) + timedelta(
                seconds=SPEAKING_UPLOAD_EXPIRY_SECONDS
            )
            renewed = repo.renew_speaking_response_session(
                response_id=UUID(str(existing["id"])),
                attempt_id=attempt_id,
                expires_at_iso=expires_at.isoformat(),
            )
            if renewed is None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail="Upload session could not be renewed.",
                )
        remaining = max(1, int((expires_at - datetime.now(UTC)).total_seconds()))
        return SpeakingResponseSession(
            response_id=UUID(str(existing["id"])),
            upload_url=generate_presigned_put_url(
                str(existing["audio_url"]),
                content_type=content_type,
                expiry=remaining,
            ),
            expires_at=expires_at,
            idempotency_key=expected_key,
            idempotent_replay=True,
        )

    response_id = uuid4()
    idempotency_key = request.idempotency_key or uuid4().hex
    expires_at = datetime.now(UTC) + timedelta(seconds=SPEAKING_UPLOAD_EXPIRY_SECONDS)
    ext = _audio_extension_for_upload(content_type)
    audio_key = (
        f"speaking/{attempt_id}/responses/"
        f"{request.sequence_number:02d}-{request.question_id}-{response_id}.{ext}"
    )
    try:
        row = repo.insert_speaking_response_session(
            attempt_id=attempt_id,
            question_id=request.question_id,
            part=request.part,
            sequence_number=request.sequence_number,
            audio_key=audio_key,
            content_type=content_type,
            duration_sec=request.duration_sec,
            size_bytes=request.size_bytes,
            idempotency_key=idempotency_key,
            expires_at_iso=expires_at.isoformat(),
        )
    except Exception:
        raced = repo.get_speaking_response(
            attempt_id=attempt_id,
            question_id=request.question_id,
        )
        if raced is None:
            raise
        return create_response_session(
            attempt_id=attempt_id,
            user_id=user_id,
            request=request,
        )
    return SpeakingResponseSession(
        response_id=UUID(str(row["id"])),
        upload_url=generate_presigned_put_url(
            audio_key,
            content_type=content_type,
            expiry=SPEAKING_UPLOAD_EXPIRY_SECONDS,
        ),
        expires_at=expires_at,
        idempotency_key=idempotency_key,
    )


def confirm_response(
    *,
    attempt_id: UUID,
    response_id: UUID,
    user_id: UUID,
    request: ConfirmSpeakingResponseRequest,
    background_tasks: BackgroundTasks | None = None,
) -> SpeakingResponsePublic:
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "speaking":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not a speaking attempt.")
    row = repo.get_speaking_response_by_id(
        attempt_id=attempt_id,
        response_id=response_id,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Speaking response not found.")
    if request.idempotency_key != str(row.get("idempotency_key") or ""):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Upload idempotency key mismatch.")
    if request.duration_sec != int(row["duration_sec"]):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Recording duration mismatch.")
    _manifest_question(
        attempt,
        question_id=UUID(str(row["question_id"])),
        part=int(row["part"]),
        sequence_number=int(row["sequence_number"]),
    )
    if str(row.get("status")) == "confirmed":
        queued = repo.queue_speaking_response_transcription(
            response_id=response_id,
            attempt_id=attempt_id,
        )
        if queued is not None:
            row = queued
            if background_tasks is not None:
                background_tasks.add_task(transcribe_response, response_id)
        return _response_to_public(row, idempotent_replay=True)
    if attempt.get("status") != "in_progress":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Attempt cannot confirm responses (status={attempt.get('status')}).",
        )

    try:
        head = object_head(str(row["audio_url"]), raise_errors=True)
    except RuntimeError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Speaking upload storage is temporarily unavailable.",
        ) from exc
    if head is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Uploaded object was not found.")
    if int(head["size"]) != int(row["size_bytes"]):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Uploaded object size mismatch.")
    actual_content_type = str(head.get("content_type") or "").lower().split(";", 1)[0]
    if actual_content_type != str(row["content_type"]):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Uploaded object content type mismatch.")

    confirmed = repo.confirm_speaking_response(
        response_id=response_id,
        attempt_id=attempt_id,
        confirmed_at_iso=datetime.now(UTC).isoformat(),
    )
    if confirmed is None:
        raced = repo.get_speaking_response_by_id(
            attempt_id=attempt_id,
            response_id=response_id,
        )
        if raced is None or str(raced.get("status")) != "confirmed":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Speaking response could not be confirmed.",
            )
        confirmed = raced
        replay = True
    else:
        replay = False
    queued = repo.queue_speaking_response_transcription(
        response_id=response_id,
        attempt_id=attempt_id,
    )
    authoritative = queued or confirmed
    if queued is not None:
        if background_tasks is not None:
            background_tasks.add_task(transcribe_response, response_id)
    return _response_to_public(authoritative, idempotent_replay=replay)


def upload_response(
    *,
    attempt_id: UUID,
    user_id: UUID,
    question_id: UUID,
    part: int,
    sequence_number: int,
    duration_sec: int,
    audio_bytes: bytes,
    content_type: str | None,
    filename: str | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> SpeakingResponsePublic:
    if duration_sec < 5 or len(audio_bytes) < 2000:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Recording is too short.")

    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "speaking":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not a speaking attempt.")

    questions, _ = _attempt_manifest(attempt)
    expected = next(
        (question for question in questions if question.id == question_id),
        None,
    )
    if expected is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Question is not part of this attempt's Speaking manifest.",
        )
    if expected.part != part or expected.sequence_number != sequence_number:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": "Response metadata does not match the Speaking manifest.",
                "expected_part": expected.part,
                "expected_sequence_number": expected.sequence_number,
            },
        )

    normalized_content_type = _normalized_audio_content_type(content_type)
    content_sha256 = hashlib.sha256(audio_bytes).hexdigest()
    existing = repo.get_speaking_response(
        attempt_id=attempt_id, question_id=question_id
    )
    if existing:
        if existing.get("idempotency_key"):
            metadata_matches = (
                int(existing["part"]) == part
                and int(existing["sequence_number"]) == sequence_number
                and int(existing["duration_sec"]) == duration_sec
                and int(existing["size_bytes"]) == len(audio_bytes)
                and str(existing["content_type"]) == normalized_content_type
            )
            if not metadata_matches:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail="A different upload session already exists for this question.",
                )

            if str(existing.get("status")) == "pending_upload":
                upload_object(
                    key=str(existing["audio_url"]),
                    body=audio_bytes,
                    content_type=normalized_content_type,
                )
                confirmed = repo.confirm_speaking_response(
                    response_id=UUID(str(existing["id"])),
                    attempt_id=attempt_id,
                    confirmed_at_iso=datetime.now(UTC).isoformat(),
                )
                if confirmed is None:
                    confirmed = repo.get_speaking_response(
                        attempt_id=attempt_id, question_id=question_id
                    )
                if confirmed is None or str(confirmed.get("status")) != "confirmed":
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        detail="Speaking response could not be confirmed.",
                    )
                existing = confirmed

            if str(existing.get("status")) == "confirmed":
                queued = repo.queue_speaking_response_transcription(
                    response_id=UUID(str(existing["id"])),
                    attempt_id=attempt_id,
                )
                authoritative = queued or existing
                if queued is not None and background_tasks is not None:
                    background_tasks.add_task(
                        transcribe_response, UUID(str(existing["id"]))
                    )
                return _response_to_public(authoritative, idempotent_replay=True)

        if str(existing.get("content_sha256")) != content_sha256:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="A different response is already stored for this question.",
            )
        queued = repo.queue_speaking_response_transcription(
            response_id=UUID(str(existing["id"])),
            attempt_id=attempt_id,
        )
        authoritative = queued or existing
        if queued is not None and background_tasks is not None:
            background_tasks.add_task(
                transcribe_response, UUID(str(existing["id"]))
            )
        return _response_to_public(authoritative, idempotent_replay=True)

    if attempt.get("status") != "in_progress":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Attempt cannot accept responses (status={attempt.get('status')}).",
        )

    ext = _audio_extension_for_upload(content_type, filename)
    audio_key = (
        f"speaking/{attempt_id}/responses/"
        f"{sequence_number:02d}-{question_id}.{ext}"
    )
    upload_object(
        key=audio_key,
        body=audio_bytes,
        content_type=normalized_content_type,
    )
    try:
        row = repo.insert_speaking_response(
            attempt_id=attempt_id,
            question_id=question_id,
            part=part,
            sequence_number=sequence_number,
            audio_key=audio_key,
            content_type=normalized_content_type,
            duration_sec=duration_sec,
            size_bytes=len(audio_bytes),
            content_sha256=content_sha256,
        )
    except Exception:
        raced = repo.get_speaking_response(
            attempt_id=attempt_id, question_id=question_id
        )
        if not raced or str(raced.get("content_sha256")) != content_sha256:
            raise
        return _response_to_public(raced, idempotent_replay=True)
    queued = repo.queue_speaking_response_transcription(
        response_id=UUID(str(row["id"])),
        attempt_id=attempt_id,
    )
    authoritative = queued or row
    if queued is not None:
        if background_tasks is not None:
            background_tasks.add_task(
                transcribe_response, UUID(str(row["id"]))
            )
    return _response_to_public(authoritative)


def list_responses(
    *, attempt_id: UUID, user_id: UUID
) -> list[SpeakingResponsePublic]:
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "speaking":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not a speaking attempt.")
    responses: list[SpeakingResponsePublic] = []
    for row in repo.list_speaking_responses(attempt_id=attempt_id):
        row_status = str(row.get("status") or "")
        recovery_status = "confirmed" if row_status in {"confirmed", "uploaded"} else "session"
        if row_status == "pending_upload" and object_head(str(row["audio_url"])) is not None:
            recovery_status = "uploaded"
        responses.append(_response_to_public(row, recovery_status=recovery_status))
    return responses


def submit_attempt(
    *,
    attempt_id: UUID,
    user_id: UUID,
    audio_bytes: bytes,
    content_type: str | None,
    student_name: str | None = None,
    duration_sec: int | None = None,
    filename: str | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> SubmitSpeakingResponse:
    if len(audio_bytes) < 1000:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Recording is too short.")

    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "speaking":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not a speaking attempt.")
    if attempt.get("status") != "in_progress":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Attempt cannot be submitted (status={attempt.get('status')}).",
        )

    mock_test_id = UUID(str(attempt["mock_test_id"]))
    part = int(attempt.get("part") or 1)
    rows = repo.list_questions_for_part(mock_test_id=mock_test_id, part=part)
    if not rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Speaking question missing.")
    question = _row_to_question(rows[0])

    ext = _audio_extension_for_upload(content_type, filename)
    audio_key = f"speaking/{attempt_id}/part-{part}/recording.{ext}"
    upload_object(
        key=audio_key,
        body=audio_bytes,
        content_type=content_type or "audio/webm",
    )

    submission_meta = {
        "part": part,
        "part_label": question.part_label or f"Part {part}",
        "prompt_title": "Introduction and interview",
        "cue_card": question.prompt,
        "duration_sec": duration_sec,
    }
    duration_estimate = _duration_band_estimate(
        duration_sec=duration_sec,
        hint_sec=question.duration_hint_sec,
    )
    submit_ai_scores: dict[str, Any] = {
        "status": "pending",
        "duration_sec": duration_sec,
    }
    if duration_estimate is not None:
        submit_ai_scores["ai_band"] = duration_estimate
        submit_ai_scores["duration_estimate"] = duration_estimate

    review = repo.insert_speaking_review(
        attempt_id=attempt_id,
        audio_key=audio_key,
        submission_meta=submission_meta,
        student_name=student_name,
        ai_scores=submit_ai_scores,
    )

    review_id = UUID(str(review["id"]))
    if background_tasks is not None:
        background_tasks.add_task(run_speaking_evaluation, review_id)
    else:
        run_speaking_evaluation(review_id)

    now = datetime.now(UTC)
    completed = repo.mark_attempt_completed(
        attempt_id, completed_at_iso=now.isoformat()
    )

    mock_next_module: str | None = None
    mock_next_part: int | None = None
    mock_speaking_complete = False

    if attempt.get("mock_attempt_id"):
        from app.services import mock_orchestrator

        progress_timing = MockProgressTiming()
        progress = mock_orchestrator.on_module_attempt_completed(
            test_attempt_id=attempt_id,
            user_id=user_id,
            attempt=completed,
            timing=progress_timing,
        )
        if progress is not None:
            mock_next_module = progress.next_module
            mock_next_part = progress.next_part
            if progress.status == "completed" or progress.next_module != "speaking":
                mock_speaking_complete = True

    return SubmitSpeakingResponse(
        attempt_id=attempt_id,
        status="completed",
        submitted_at=now,
        review_id=UUID(str(review["id"])),
        mock_next_module=mock_next_module,
        mock_next_part=mock_next_part,
        mock_speaking_complete=mock_speaking_complete,
    )


def finalize_attempt(
    *,
    attempt_id: UUID,
    user_id: UUID,
    manifest_hash: str,
    student_name: str | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> SubmitSpeakingResponse:
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "speaking":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not a speaking attempt.")

    questions, frozen_hash = _attempt_manifest(attempt)
    if manifest_hash != frozen_hash:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Speaking manifest changed or does not belong to this attempt.",
        )

    existing_review = repo.get_speaking_review_for_attempt(attempt_id)
    if attempt.get("status") == "completed":
        if not existing_review:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Completed attempt has no Speaking review.",
            )
        completed_at = _parse_started_at(
            {"started_at": attempt.get("completed_at")}
        )
        return SubmitSpeakingResponse(
            attempt_id=attempt_id,
            status="completed",
            submitted_at=completed_at,
            review_id=UUID(str(existing_review["id"])),
            mock_speaking_complete=True,
        )
    if attempt.get("status") != "in_progress":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Attempt cannot be finalized (status={attempt.get('status')}).",
        )

    all_responses = repo.list_speaking_responses(attempt_id=attempt_id)
    responses = [
        row for row in all_responses if str(row.get("status")) == "confirmed"
    ]
    expected_ids = {str(question.id) for question in questions}
    received_ids = {str(row["question_id"]) for row in responses}
    missing = [
        str(question.id)
        for question in questions
        if str(question.id) not in received_ids
    ]
    unexpected = sorted(received_ids - expected_ids)
    if missing or unexpected or len(responses) != len(questions):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": "All expected Speaking responses are required.",
                "expected_response_count": len(questions),
                "received_response_count": len(responses),
                "missing_question_ids": missing,
                "unexpected_question_ids": unexpected,
            },
        )

    response_meta = [
        {
            "response_id": str(row["id"]),
            "question_id": str(row["question_id"]),
            "part": int(row["part"]),
            "sequence_number": int(row["sequence_number"]),
            "duration_sec": int(row["duration_sec"]),
            "audio_url": str(row["audio_url"]),
            "transcription_status": str(
                row.get("transcription_status") or "not_queued"
            ),
            "transcript": row.get("transcript"),
            "fluency_metrics": row.get("fluency_metrics"),
        }
        for row in responses
    ]
    completed_transcriptions = [
        {**row, "response_id": str(row["id"])}
        for row in responses
        if str(row.get("transcription_status")) == "completed"
    ]
    metrics_snapshot = (
        aggregate_fluency_metrics(completed_transcriptions)
        if completed_transcriptions
        else None
    )
    progress = repo.transcription_progress(attempt_id=attempt_id)
    initial_ai_scores: dict[str, Any] = {
        "status": "pending_multi_response",
        "response_count": len(responses),
        "transcription_progress": progress,
    }
    if metrics_snapshot:
        initial_ai_scores.update(
            {
                "fluency_metrics": metrics_snapshot["attempt_metrics"],
                "part_metrics": metrics_snapshot["part_metrics"],
                "response_metrics": metrics_snapshot["response_metrics"],
                "metrics_version": metrics_snapshot["version"],
                "metrics_source_checksum": metrics_snapshot["source_checksum"],
                "metrics_source_checksums": metrics_snapshot["source_checksums"],
            }
        )
    review = existing_review
    if review is None:
        review = repo.insert_speaking_review(
            attempt_id=attempt_id,
            audio_key=str(responses[0]["audio_url"]),
            submission_meta={
                "manifest_hash": frozen_hash,
                "response_count": len(responses),
                "responses": response_meta,
                "parts": sorted({int(row["part"]) for row in responses}),
            },
            student_name=student_name,
            ai_scores=initial_ai_scores,
        )
    else:
        existing_scores = review.get("ai_scores")
        initial_ai_scores = {
            **(existing_scores if isinstance(existing_scores, dict) else {}),
            **initial_ai_scores,
        }
    completed_transcript = "\n\n".join(
        str(row.get("transcript") or "").strip()
        for row in completed_transcriptions
        if str(row.get("transcript") or "").strip()
    )
    repo.update_speaking_review_evaluation(
        review_id=UUID(str(review["id"])),
        transcript=completed_transcript or None,
        ai_scores=initial_ai_scores,
    )
    review_id = UUID(str(review["id"]))
    if completed_transcriptions and len(completed_transcriptions) == len(responses):
        if background_tasks is not None:
            background_tasks.add_task(run_speaking_evaluation, review_id)
        else:
            run_speaking_evaluation(review_id)

    now = datetime.now(UTC)
    completed = repo.mark_attempt_completed(
        attempt_id, completed_at_iso=now.isoformat()
    )
    mock_next_module: str | None = None
    mock_next_part: int | None = None
    mock_speaking_complete = False
    if attempt.get("mock_attempt_id"):
        from app.services import mock_orchestrator

        progress = mock_orchestrator.on_module_attempt_completed(
            test_attempt_id=attempt_id,
            user_id=user_id,
            attempt=completed,
            timing=MockProgressTiming(),
        )
        if progress is not None:
            mock_next_module = progress.next_module
            mock_next_part = progress.next_part
            mock_speaking_complete = (
                progress.status == "completed"
                or progress.next_module != "speaking"
            )

    return SubmitSpeakingResponse(
        attempt_id=attempt_id,
        status="completed",
        submitted_at=now,
        review_id=review_id,
        mock_next_module=mock_next_module,
        mock_next_part=mock_next_part,
        mock_speaking_complete=mock_speaking_complete,
    )


def get_pending_status(
    *,
    attempt_id: UUID,
    user_id: UUID,
    student_name: str | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> SpeakingPendingResponse:
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "speaking":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not a speaking attempt.")

    review = repo.get_speaking_review_for_attempt(attempt_id)
    if not review:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No speaking submission found.")
    if background_tasks is not None:
        background_tasks.add_task(reconcile_attempt_transcriptions, attempt_id)

    review_status = str(review.get("status") or "pending")
    human_band = review.get("human_band")
    band_val = float(human_band) if human_band is not None else None

    ai_scores = review.get("ai_scores") or {}
    ai_status = (
        str(ai_scores.get("status"))
        if isinstance(ai_scores, dict) and ai_scores.get("status")
        else None
    )
    evaluation_status = (
        str(review.get("evaluation_status"))
        if review.get("evaluation_status")
        else None
    )
    ai_complete = (
        evaluation_status == "completed"
        and ai_status in ("ai_complete", "ai_stub")
    )
    ai_band: float | None = None
    if ai_complete:
        candidate = _parse_optional_float(ai_scores.get("ai_band"))
        if (
            candidate is not None
            and 0 <= candidate <= 9
            and candidate * 2 == round(candidate * 2)
        ):
            ai_band = candidate
    evaluation = (
        ai_scores.get("evaluation")
        if ai_complete and isinstance(ai_scores.get("evaluation"), dict)
        else {}
    )
    ai_criteria = {
        key: float(ai_scores[key])
        for key in ("fluency", "lexical", "grammar", "pronunciation")
        if isinstance(ai_scores.get(key), (int, float))
    }
    ai_strengths = [
        str(item)
        for item in evaluation.get("strengths", [])
        if isinstance(item, str) and item.strip()
    ]
    ai_improvements = [
        str(item)
        for item in evaluation.get("improvements", [])
        if isinstance(item, str) and item.strip()
    ]
    advice = evaluation.get("next_band_advice")
    next_band_advice = (
        str(advice).strip() if isinstance(advice, str) and advice.strip() else None
    )
    ai_parts = (
        [item for item in evaluation.get("part_performance", []) if isinstance(item, dict)]
        if ai_complete
        else []
    )
    ai_evidence = (
        [item for item in evaluation.get("evidence_quotes", []) if isinstance(item, dict)]
        if ai_complete
        else []
    )
    ai_patterns = (
        [
            item
            for item in evaluation.get("recurring_patterns", [])
            if isinstance(item, dict)
        ]
        if ai_complete
        else []
    )
    ai_fluency = (
        dict(ai_scores.get("attempt_metrics") or ai_scores.get("fluency_metrics") or {})
        if ai_complete
        else {}
    )
    ai_part_metrics = (
        dict(ai_scores.get("part_metrics") or {}) if ai_complete else {}
    )

    transcription_progress = repo.transcription_progress(attempt_id=attempt_id)
    release = resolve_release_state(
        attempt=attempt,
        review=review,
        transcription_progress=transcription_progress,
    )

    if release.release_state == "released" and band_val is not None:
        score_source = "human"
        message = f"Your Speaking band is {band_val:.1f}."
    elif release.release_state == "withdrawn":
        score_source = "unavailable"
        message = (
            "Your Speaking result was withdrawn for examiner review. "
            "An updated result will be published when the review is complete."
        )
    elif ai_band is not None:
        score_source = "ai_estimate"
        message = (
            f"Your provisional AI Speaking estimate is {ai_band:.1f}. "
            "A certified examiner is reviewing the official result."
        )
    elif ai_status == "ai_failed" or evaluation_status == "failed":
        score_source = "failed"
        message = (
            "AI analysis could not finish. Your recording is safe and remains "
            "queued for certified examiner review."
        )
    elif release.release_state == "processing":
        score_source = "processing"
        message = (
            "Your recording is being processed. A certified examiner will review "
            "your speaking and confirm your band within 24 hours."
        )
    else:
        score_source = "processing"
        message = (
            "Your Speaking score is coming soon. A certified examiner is reviewing "
            "your recording — you will receive your band within 24 hours."
        )

    completed_raw = attempt.get("completed_at")
    submitted_at = None
    if completed_raw:
        submitted_at = (
            datetime.fromisoformat(str(completed_raw).replace("Z", "+00:00"))
            if isinstance(completed_raw, str)
            else completed_raw
        )

    manifest, _ = _attempt_manifest(attempt)
    questions_by_id = {str(question.id): question for question in manifest}
    transcript_responses: list[SpeakingPendingTranscriptResponse] = []
    rows = sorted(
        repo.list_speaking_responses(attempt_id=attempt_id),
        key=lambda row: (
            int(row.get("sequence_number") or 0),
            str(row.get("id") or ""),
        ),
    )
    for row in rows:
        if str(row.get("status") or "") != "confirmed":
            continue
        question = questions_by_id.get(str(row.get("question_id") or ""))
        part = int(row.get("part") or (question.part if question else 1))
        sequence = int(
            row.get("sequence_number")
            or (question.sequence_number if question else 1)
        )
        transcription_status = str(
            row.get("transcription_status") or "not_queued"
        )
        transcript_responses.append(
            SpeakingPendingTranscriptResponse(
                id=UUID(str(row["id"])),
                question_id=UUID(str(row["question_id"])),
                part=part,
                sequence=max(1, sequence),
                prompt=question.prompt if question else "",
                duration_sec=max(0, int(row.get("duration_sec") or 0)),
                transcription_status=transcription_status,
                transcript=str(row.get("transcript") or ""),
                transcription_error=(
                    "Transcription unavailable after retry."
                    if transcription_status == "failed"
                    else None
                ),
            )
        )

    return SpeakingPendingResponse(
        attempt_id=attempt_id,
        status=str(attempt.get("status") or "completed"),
        review_status=review_status,
        human_band=band_val,
        ai_status=ai_status,
        evaluation_status=evaluation_status,
        score_source=score_source,
        ai_band=ai_band,
        ai_criteria=ai_criteria,
        ai_strengths=ai_strengths,
        ai_improvements=ai_improvements,
        next_band_advice=next_band_advice,
        ai_parts=ai_parts,
        ai_evidence=ai_evidence,
        ai_patterns=ai_patterns,
        ai_fluency=ai_fluency,
        ai_part_metrics=ai_part_metrics,
        responses=transcript_responses,
        submitted_at=submitted_at,
        student_name=student_name,
        message=message,
        transcription_progress=transcription_progress,
        **release.model_dump(),
    )


def _parse_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_human_criteria(raw: Any) -> SpeakingHumanCriteria | None:
    if not isinstance(raw, dict):
        return None
    try:
        return SpeakingHumanCriteria(
            fluency=float(raw["fluency"]),
            lexical=float(raw["lexical"]),
            grammar=float(raw["grammar"]),
            pronunciation=float(raw["pronunciation"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _parse_optional_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def resolve_release_state(
    *,
    attempt: dict[str, Any],
    review: dict[str, Any],
    transcription_progress: dict[str, int] | None = None,
) -> SpeakingReleaseMetadata:
    """Resolve the single authoritative public release state."""
    review_status = str(review.get("status") or "pending")
    criteria = _parse_human_criteria(review.get("human_criteria_scores"))
    criteria_valid = criteria is not None and all(
        0 <= value <= 9
        for value in (
            criteria.fluency,
            criteria.lexical,
            criteria.grammar,
            criteria.pronunciation,
        )
    )
    band = _parse_optional_float(review.get("human_band"))
    released = (
        review_status == "completed"
        and band is not None
        and 0 <= band <= 9
        and criteria_valid
    )

    reviewer: SpeakingReviewerPublic | None = None
    display_name = review.get("reviewer_display_name")
    if released and display_name:
        reviewer = SpeakingReviewerPublic(
            display_name=str(display_name),
            credential_label=str(
                review.get("reviewer_credential_label")
                or "Certified IELTS Examiner"
            ),
        )

    released_at = _parse_optional_datetime(
        review.get("released_at") or review.get("reviewed_at")
    )
    metadata = {
        "report_available": released,
        "released_at": released_at,
        "approval_version": int(review.get("approval_version") or 0),
        "reviewer": reviewer,
    }
    if released:
        return SpeakingReleaseMetadata(release_state="released", **metadata)
    if review.get("reopened_at"):
        return SpeakingReleaseMetadata(release_state="withdrawn", **metadata)

    progress = transcription_progress or {}
    total = int(progress.get("total") or 0)
    terminal_transcriptions = int(progress.get("completed") or 0) + int(
        progress.get("failed") or 0
    )
    transcription_active = total > terminal_transcriptions

    evaluation_status = review.get("evaluation_status")
    if evaluation_status is not None:
        evaluation_active = str(evaluation_status) in {
            "not_queued",
            "queued",
            "processing",
            "retry_wait",
        }
    else:
        ai_scores = (
            review.get("ai_scores")
            if isinstance(review.get("ai_scores"), dict)
            else {}
        )
        evaluation_active = str(ai_scores.get("status") or "") in {
            "pending",
            "pending_multi_response",
            "processing",
            "retry_wait",
        }

    attempt_active = str(attempt.get("status") or "") == "in_progress"
    state = (
        "processing"
        if attempt_active or transcription_active or evaluation_active
        else "awaiting_examiner"
    )
    return SpeakingReleaseMetadata(release_state=state, **metadata)


def _parse_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_fluency_metrics(raw: Any) -> SpeakingFluencyMetrics | None:
    if not isinstance(raw, dict):
        return None
    return SpeakingFluencyMetrics(
        words_per_minute=_parse_optional_float(raw.get("words_per_minute")),
        total_speaking_seconds=_parse_optional_float(raw.get("total_speaking_seconds")),
        long_pauses=_parse_optional_int(raw.get("long_pauses")),
        response_count=_parse_optional_int(raw.get("response_count")),
        questions_asked=_parse_optional_int(raw.get("questions_asked")),
        word_count=_parse_optional_int(raw.get("word_count")),
    )


def _parse_pause_markers(ai_scores: dict[str, Any]) -> list[SpeakingPauseMarker]:
    words = ai_scores.get("words")
    if not isinstance(words, list):
        return []
    markers = long_pause_markers(words)
    out: list[SpeakingPauseMarker] = []
    for item in markers:
        try:
            out.append(
                SpeakingPauseMarker(
                    after_word=str(item["after_word"]),
                    gap_sec=float(item["gap_sec"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


SPEAKING_REPORT_AUDIO_TTL_SECONDS = 60 * 60


def _safe_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.replace("\x00", "").split())
    return text or None


def _report_words(raw: Any, transcript: str) -> list[SpeakingTranscriptWord]:
    if not isinstance(raw, list) or not transcript:
        return []
    words: list[SpeakingTranscriptWord] = []
    previous_end = 0
    search_from = 0
    folded_transcript = transcript.casefold()
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = _safe_text(item.get("word") or item.get("text"))
        try:
            start_ms = round(float(item["start"]) * 1000)
            end_ms = round(float(item["end"]) * 1000)
        except (KeyError, TypeError, ValueError):
            continue
        if (
            not text
            or start_ms < previous_end
            or end_ms < start_ms
            or folded_transcript.find(text.casefold(), search_from) < 0
        ):
            continue
        char_at = folded_transcript.find(text.casefold(), search_from)
        search_from = char_at + len(text)
        words.append(
            SpeakingTranscriptWord(text=text, start_ms=start_ms, end_ms=end_ms)
        )
        previous_end = end_ms
    return words


def _response_pauses(words: list[SpeakingTranscriptWord]) -> list[SpeakingResponsePause]:
    pauses: list[SpeakingResponsePause] = []
    for index, (previous, current) in enumerate(zip(words, words[1:])):
        duration = current.start_ms - previous.end_ms
        if duration <= 2000:
            continue
        pauses.append(
            SpeakingResponsePause(
                after_word_index=index,
                start_ms=previous.end_ms,
                end_ms=current.start_ms,
                duration_ms=duration,
            )
        )
        if len(pauses) == 8:
            break
    return pauses


def _find_word_char_ranges(
    transcript: str, words: list[SpeakingTranscriptWord]
) -> list[tuple[int, int, SpeakingTranscriptWord]]:
    ranges: list[tuple[int, int, SpeakingTranscriptWord]] = []
    cursor = 0
    folded = transcript.casefold()
    for word in words:
        start = folded.find(word.text.casefold(), cursor)
        if start < 0:
            return []
        end = start + len(word.text)
        ranges.append((start, end, word))
        cursor = end
    return ranges


def _evidence_span(
    transcript: str,
    quote: str,
    words: list[SpeakingTranscriptWord],
) -> SpeakingEvidenceSpan | None:
    if transcript.count(quote) != 1:
        return None
    char_start = transcript.index(quote)
    char_end = char_start + len(quote)
    overlapping = [
        word
        for start, end, word in _find_word_char_ranges(transcript, words)
        if start < char_end and end > char_start
    ]
    if not overlapping:
        return None
    return SpeakingEvidenceSpan(
        char_start=char_start,
        char_end=char_end,
        start_ms=overlapping[0].start_ms,
        end_ms=overlapping[-1].end_ms,
    )


def _validated_evaluation(ai_scores: dict[str, Any]) -> SpeakingEvaluation | None:
    raw = ai_scores.get("evaluation")
    if not isinstance(raw, dict):
        return None
    try:
        return SpeakingEvaluation.model_validate(raw)
    except Exception:
        return None


def _build_scores(
    overall: float,
    criteria: SpeakingHumanCriteria,
    target: float | None,
) -> SpeakingReportScores:
    values = {
        "fluency": criteria.fluency,
        "lexical": criteria.lexical,
        "grammar": criteria.grammar,
        "pronunciation": criteria.pronunciation,
    }
    results: dict[str, SpeakingCriterionResult] = {}
    for key, band in values.items():
        gap = round(target - band, 1) if target is not None else None
        results[key] = SpeakingCriterionResult(
            band=band,
            target_band=target,
            target_gap=gap,
        )
    biggest_gap = None
    if target is not None:
        key, result = max(
            results.items(),
            key=lambda item: (item[1].target_gap or 0, -list(results).index(item[0])),
        )
        biggest_gap = SpeakingBiggestGap(
            criterion=key,  # type: ignore[arg-type]
            gap=float(result.target_gap or 0),
        )
    return SpeakingReportScores(
        overall=overall,
        criteria=results,  # type: ignore[arg-type]
        biggest_gap=biggest_gap,
    )


def _report_evidence(
    evaluation: SpeakingEvaluation | None,
    responses: list[SpeakingReportResponseItem],
) -> list[SpeakingReportEvidence]:
    if evaluation is None:
        return []
    by_id = {str(item.id): item for item in responses}
    evidence: list[SpeakingReportEvidence] = []
    for item in evaluation.evidence_quotes:
        response = by_id.get(str(item.response_id or ""))
        rich = [item.issue, item.title, item.explanation, item.suggestion]
        if (
            response is None
            or str(response.question_id) != str(item.question_id or "")
            or response.part != item.part
            or item.quote not in response.transcript
            or any(not _safe_text(value) for value in rich)
        ):
            continue
        evidence.append(
            SpeakingReportEvidence(
                response_id=response.id,
                question_id=response.question_id,
                part=item.part,
                criterion=item.criterion,
                polarity=item.polarity,
                quote=item.quote,
                issue=_safe_text(item.issue) or "",
                title=_safe_text(item.title) or "",
                explanation=_safe_text(item.explanation) or "",
                suggestion=_safe_text(item.suggestion) or "",
                span=_evidence_span(
                    response.transcript, item.quote, response.transcript_words
                ),
                advisory_only=item.criterion == "P",
                inference_source=(
                    "transcript_inferred" if item.criterion == "P" else None
                ),
                confidence=(
                    evaluation.band_scores.P_confidence
                    if item.criterion == "P"
                    else None
                ),
            )
        )
    return evidence


def _report_patterns(
    evaluation: SpeakingEvaluation | None,
    responses: list[SpeakingReportResponseItem],
) -> list[SpeakingReportPattern]:
    if evaluation is None:
        return []
    patterns: list[SpeakingReportPattern] = []
    for item in evaluation.recurring_patterns:
        examples: list[SpeakingPatternExample] = []
        grounded_phrases: set[str] = set()
        occurrence_count = 0
        for raw_example in item.examples:
            text = _safe_text(raw_example)
            if not text:
                continue
            bound = next(
                (
                    response
                    for response in responses
                    if re.search(re.escape(text), response.transcript, re.IGNORECASE)
                ),
                None,
            )
            if bound is not None:
                examples.append(
                    SpeakingPatternExample(
                        text=text,
                        response_id=bound.id,
                    )
                )
            folded = text.casefold()
            if bound is not None and folded not in grounded_phrases:
                grounded_phrases.add(folded)
                occurrence_count += sum(
                    len(re.findall(re.escape(text), response.transcript, re.IGNORECASE))
                    for response in responses
                )
        patterns.append(
            SpeakingReportPattern(
                pattern=_safe_text(item.pattern) or item.pattern,
                criterion=item.criterion,
                frequency=item.frequency,
                occurrence_count=occurrence_count if grounded_phrases else None,
                occurrence_count_semantics=(
                    "grounded_example_matches" if grounded_phrases else None
                ),
                examples=examples,
            )
        )
    return patterns


def _canonical_report_fluency(
    responses: list[SpeakingReportResponseItem],
    *,
    snapshot_overall: SpeakingFluencyMetrics | None,
    snapshot_parts: dict[str, SpeakingFluencyMetrics],
    snapshot_responses: Any,
) -> SpeakingReportFluency:
    """Prefer metrics carried by released responses over evaluation snapshots."""
    grounded_rows = [
        {
            "response_id": str(response.id),
            "part": response.part,
            "sequence_number": response.sequence,
            "fluency_metrics": response.metrics.model_dump(),
        }
        for response in responses
        if response.metrics is not None
    ]
    if grounded_rows:
        aggregate = aggregate_fluency_metrics(grounded_rows)
        return SpeakingReportFluency(
            overall=_parse_fluency_metrics(aggregate["attempt_metrics"]),
            parts={
                str(part): parsed
                for part, raw in aggregate["part_metrics"].items()
                if (parsed := _parse_fluency_metrics(raw)) is not None
            },
            responses=[
                SpeakingResponseMetrics.model_validate(item)
                for item in aggregate["response_metrics"]
            ],
            source="response_metrics",
            complete=bool(responses) and len(grounded_rows) == len(responses),
        )

    parsed_snapshot_responses: list[SpeakingResponseMetrics] = []
    if isinstance(snapshot_responses, list):
        for item in snapshot_responses:
            try:
                parsed_snapshot_responses.append(
                    SpeakingResponseMetrics.model_validate(item)
                )
            except Exception:
                continue
    if snapshot_overall is not None or snapshot_parts or parsed_snapshot_responses:
        return SpeakingReportFluency(
            overall=snapshot_overall,
            parts=snapshot_parts,
            responses=parsed_snapshot_responses,
            source="evaluation_snapshot",
            complete=False,
        )
    return SpeakingReportFluency(source="unavailable", complete=False)


def get_speaking_report(
    *,
    attempt_id: UUID,
    user_id: UUID,
    student_name: str | None = None,
) -> SpeakingReportResponse:
    """Build the privacy-safe v2 report after the authoritative release gate."""
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "speaking":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not a speaking attempt.")

    review = repo.get_speaking_review_for_attempt(attempt_id)
    if not review:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No speaking submission found.")
    release_metadata = resolve_release_state(attempt=attempt, review=review)
    human_criteria = _parse_human_criteria(review.get("human_criteria_scores"))
    human_band = _parse_optional_float(review.get("human_band"))
    released_at = release_metadata.released_at
    if (
        not release_metadata.report_available
        or human_band is None
        or human_criteria is None
        or released_at is None
        or release_metadata.approval_version < 1
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Speaking report is not ready — waiting for human review.",
        )

    manifest = []
    if isinstance(attempt.get("speaking_manifest"), list) and attempt.get(
        "speaking_manifest"
    ):
        manifest, _ = _attempt_manifest(attempt)
    manifest_by_id = {str(question.id): question for question in manifest}
    rows = sorted(
        repo.list_speaking_responses(attempt_id=attempt_id),
        key=lambda row: (int(row.get("sequence_number") or 0), str(row.get("id") or "")),
    )
    report_responses: list[SpeakingReportResponseItem] = []
    signed_at = datetime.now(UTC)
    for row in rows:
        if str(row.get("status")) != "confirmed":
            continue
        question = manifest_by_id.get(str(row.get("question_id") or ""))
        if (
            question is None
            or int(row.get("part") or 0) != question.part
            or int(row.get("sequence_number") or 0) != question.sequence_number
        ):
            continue
        transcript = _safe_text(row.get("transcript")) or ""
        words = _report_words(row.get("transcript_words"), transcript)
        audio_url = None
        audio_expires_at = None
        if row.get("audio_url"):
            try:
                candidate_url = generate_signed_url(
                    str(row["audio_url"]), expiry=SPEAKING_REPORT_AUDIO_TTL_SECONDS
                )
                if candidate_url:
                    audio_url = candidate_url
                    audio_expires_at = signed_at + timedelta(
                        seconds=SPEAKING_REPORT_AUDIO_TTL_SECONDS
                    )
            except Exception:
                pass
        report_responses.append(
            SpeakingReportResponseItem(
                id=UUID(str(row["id"])),
                question_id=question.id,
                part=question.part,
                sequence=question.sequence_number,
                prompt=question.prompt,
                duration_sec=max(0, int(row.get("duration_sec") or 0)),
                transcript=transcript,
                transcript_words=words,
                pause_markers=_response_pauses(words),
                audio_url=audio_url,
                audio_expires_at=audio_expires_at,
                metrics=_parse_fluency_metrics(row.get("fluency_metrics")),
            )
        )

    ai_scores = review.get("ai_scores") if isinstance(review.get("ai_scores"), dict) else {}
    evaluation = _validated_evaluation(ai_scores)
    raw_part_metrics = ai_scores.get("part_metrics")
    part_metrics: dict[str, SpeakingFluencyMetrics] = {}
    if isinstance(raw_part_metrics, dict):
        for key, value in raw_part_metrics.items():
            parsed = _parse_fluency_metrics(value)
            if parsed is not None:
                part_metrics[str(key)] = parsed
    attempt_metrics = _parse_fluency_metrics(ai_scores.get("fluency_metrics"))
    if not part_metrics and attempt_metrics is not None:
        part_metrics[str(int(attempt.get("part") or 1))] = attempt_metrics
    fluency_summary = _canonical_report_fluency(
        report_responses,
        snapshot_overall=attempt_metrics,
        snapshot_parts=part_metrics,
        snapshot_responses=ai_scores.get("response_metrics"),
    )
    attempt_metrics = fluency_summary.overall
    part_metrics = fluency_summary.parts
    part_performance = (
        {item.part: item for item in evaluation.part_performance}
        if evaluation is not None
        else {}
    )
    parts = [
        SpeakingReportPart(
            part=part_number,
            label=SPEAKING_PART_LABELS[part_number],
            ai_band=(
                part_performance[part_number].band_estimate
                if part_number in part_performance
                else None
            ),
            ai_note=(
                _safe_text(part_performance[part_number].note)
                if part_number in part_performance
                else None
            ),
            metrics=part_metrics.get(str(part_number)),
            response_ids=[
                response.id
                for response in report_responses
                if response.part == part_number
            ],
        )
        for part_number in (1, 2, 3)
    ]

    target = _parse_optional_float(review.get("student_target_band_at_release"))
    snapshot_name = _safe_text(review.get("student_display_name_at_release"))
    evidence = _report_evidence(evaluation, report_responses)
    patterns = _report_patterns(evaluation, report_responses)
    unavailable: list[str] = []
    if evaluation is None:
        unavailable.extend(["parts.ai", "evidence", "patterns", "summary.ai"])
    elif not evidence:
        unavailable.append("evidence")
    if any(not response.transcript for response in report_responses):
        unavailable.append("responses.transcripts")
    if any(response.audio_url is None for response in report_responses):
        unavailable.append("responses.audio")
    if not report_responses:
        unavailable.append("responses")
    if fluency_summary.overall is None:
        unavailable.append("fluency")
    elif not fluency_summary.complete:
        unavailable.append("fluency.complete")
    analysis_status = (
        "complete"
        if not unavailable
        else "unavailable"
        if evaluation is None and not report_responses
        else "degraded"
    )

    submitted_at = _parse_optional_datetime(attempt.get("completed_at"))
    mock = attempt.get("mock_tests") if isinstance(attempt.get("mock_tests"), dict) else {}
    notes = _safe_text(review.get("reviewer_notes"))
    summary = SpeakingReportSummary(
        strengths=(
            [_safe_text(item) for item in evaluation.strengths if _safe_text(item)]
            if evaluation
            else []
        ),
        improvements=(
            [_safe_text(item) for item in evaluation.improvements if _safe_text(item)]
            if evaluation
            else []
        ),
        vocabulary=(
            [
                _safe_text(item)
                for item in evaluation.vocabulary_highlights
                if _safe_text(item)
            ]
            if evaluation
            else []
        ),
        next_advice=(
            _safe_text(evaluation.next_band_advice) if evaluation else None
        ),
        examiner_note=notes,
    )
    sanitized_evaluation = (
        evaluation.model_dump(exclude={"reviewer_flags"}) if evaluation else None
    )
    legacy_response_metrics = [
        {
            "response_id": response.id,
            "part": response.part,
            "sequence_number": response.sequence,
            **response.metrics.model_dump(),
        }
        for response in report_responses
        if response.metrics is not None
    ]
    legacy_transcript = "\n\n".join(
        response.transcript for response in report_responses if response.transcript
    ) or None
    legacy_pause_markers = [
        SpeakingPauseMarker(
            after_word=response.transcript_words[pause.after_word_index].text,
            gap_sec=round(pause.duration_ms / 1000, 1),
        )
        for response in report_responses
        for pause in response.pause_markers
    ]
    legacy_part = report_responses[0].part if report_responses else int(attempt.get("part") or 1)
    return SpeakingReportResponse(
        attempt=SpeakingReportAttempt(
            id=attempt_id,
            mock_test_id=(
                UUID(str(attempt["mock_test_id"])) if attempt.get("mock_test_id") else None
            ),
            mock_attempt_id=(
                UUID(str(attempt["mock_attempt_id"]))
                if attempt.get("mock_attempt_id")
                else None
            ),
            mock_title=_safe_text(mock.get("title")),
            test_number=_parse_optional_int(mock.get("catalog_number")),
            submitted_at=submitted_at,
        ),
        student=SpeakingReportStudent(
            display_name=snapshot_name,
            target_band_at_release=target,
        ),
        release=SpeakingReportRelease(
            released_at=released_at,
            approval_version=release_metadata.approval_version,
            reviewer=release_metadata.reviewer,
        ),
        scores=_build_scores(human_band, human_criteria, target),
        parts=parts,
        responses=report_responses,
        fluency_summary=fluency_summary,
        pronunciation_advisory=SpeakingPronunciationAdvisory(
            ai_confidence=(
                evaluation.band_scores.P_confidence if evaluation else None
            ),
            ai_low_confidence=(
                evaluation is None or evaluation.band_scores.P_confidence < 0.7
            ),
        ),
        evidence=evidence,
        patterns=patterns,
        summary=summary,
        analysis=SpeakingReportAnalysis(
            status=analysis_status,  # type: ignore[arg-type]
            unavailable_sections=unavailable,
        ),
        attempt_id=attempt_id,
        status=str(attempt.get("status") or "completed"),
        review_status=str(review.get("status") or "completed"),
        overall_band=human_band,
        human_verified=True,
        human_criteria_scores=human_criteria,
        ai_band=_parse_optional_float(ai_scores.get("ai_band")),
        fluency=_parse_optional_float(ai_scores.get("fluency")),
        lexical=_parse_optional_float(ai_scores.get("lexical")),
        grammar=_parse_optional_float(ai_scores.get("grammar")),
        pronunciation=_parse_optional_float(ai_scores.get("pronunciation")),
        evaluation=sanitized_evaluation,
        fluency_metrics=attempt_metrics,
        attempt_metrics=attempt_metrics,
        part_metrics=part_metrics,
        response_metrics=legacy_response_metrics,
        transcription_progress=(
            ai_scores.get("transcription_progress")
            if isinstance(ai_scores.get("transcription_progress"), dict)
            else None
        ),
        pause_markers=legacy_pause_markers,
        transcript=legacy_transcript,
        audio_play_url=(
            report_responses[0].audio_url if report_responses else None
        ),
        ai_status=(
            str(ai_scores.get("status")) if ai_scores.get("status") else None
        ),
        submitted_at=submitted_at,
        student_name=snapshot_name or student_name,
        reviewer_notes=notes,
        part=legacy_part,
        **release_metadata.model_dump(),
    )
