"""Business logic for the Speaking module."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, status

from app.config import get_settings
from app.schemas.test_engine import TestSummary
from app.services.mock_progress_timing import MockProgressTiming
from app.speaking import repository as repo
from app.speaking.constants import SPEAKING_DURATION_MINUTES, SPEAKING_PART1_RECORD_SECONDS
from app.speaking.schemas import (
    SpeakingPendingResponse,
    SpeakingQuestionPublic,
    StartSpeakingResponse,
    SubmitSpeakingResponse,
)
from app.storage.r2 import upload_object
from app.speaking.ai_evaluator import run_speaking_evaluation


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
    return SpeakingQuestionPublic(
        id=UUID(str(row["id"])),
        question_number=int(row.get("question_number") or 1),
        question_type=str(row.get("question_type") or "speaking_part1"),
        prompt=str(row.get("prompt") or ""),
        part=int(row.get("part") or 1),
        duration_hint_sec=int(opts.get("duration_hint_sec") or SPEAKING_PART1_RECORD_SECONDS),
        part_label=str(opts.get("part_label") or "Part 1"),
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

    existing = repo.find_in_progress_speaking_attempt(
        user_id=user_id,
        mock_test_id=mock_test_id,
        part=part,
        mock_attempt_id=mock_attempt_id,
    )
    if existing and force_new:
        repo.abandon_speaking_attempt(attempt_id=UUID(str(existing["id"])))
        existing = None

    test_row = repo.get_mock_test(mock_test_id, allow_unpublished=_is_dev())
    rows = repo.list_questions_for_part(mock_test_id=mock_test_id, part=part)
    if not rows:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="No speaking question configured for this mock.",
        )
    question = _row_to_question(rows[0])
    test = TestSummary(
        id=UUID(str(test_row["id"])),
        title=str(test_row["title"]),
        description=test_row.get("description"),
    )

    if existing:
        return StartSpeakingResponse(
            attempt_id=UUID(str(existing["id"])),
            started_at=_parse_started_at(existing),
            server_time=datetime.now(UTC),
            status=str(existing.get("status", "in_progress")),
            part=part,
            duration_seconds=SPEAKING_DURATION_MINUTES * 60,
            resumed=True,
            test=test,
            question=question,
            student_name=student_name,
        )

    row = repo.insert_speaking_attempt(
        user_id=user_id,
        mock_test_id=mock_test_id,
        mock_attempt_id=mock_attempt_id,
        part=part,
    )
    return StartSpeakingResponse(
        attempt_id=UUID(str(row["id"])),
        started_at=_parse_started_at(row),
        server_time=datetime.now(UTC),
        status=str(row.get("status", "in_progress")),
        part=part,
        duration_seconds=SPEAKING_DURATION_MINUTES * 60,
        resumed=False,
        test=test,
        question=question,
        student_name=student_name,
    )


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


def get_pending_status(
    *,
    attempt_id: UUID,
    user_id: UUID,
    student_name: str | None = None,
) -> SpeakingPendingResponse:
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "speaking":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not a speaking attempt.")

    review = repo.get_speaking_review_for_attempt(attempt_id)
    if not review:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No speaking submission found.")

    review_status = str(review.get("status") or "pending")
    human_band = review.get("human_band")
    band_val = float(human_band) if human_band is not None else None

    ai_scores = review.get("ai_scores") or {}
    ai_status = (
        str(ai_scores.get("status"))
        if isinstance(ai_scores, dict) and ai_scores.get("status")
        else None
    )

    if review_status == "completed" and band_val is not None:
        message = f"Your Speaking band is {band_val:.1f}."
    elif ai_status == "pending":
        message = (
            "Your recording is being processed. A certified examiner will review "
            "your speaking and confirm your band within 24 hours."
        )
    else:
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

    return SpeakingPendingResponse(
        attempt_id=attempt_id,
        status=str(attempt.get("status") or "completed"),
        review_status=review_status,
        human_band=band_val,
        ai_status=ai_status,
        submitted_at=submitted_at,
        student_name=student_name,
        message=message,
    )
