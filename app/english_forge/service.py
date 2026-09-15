"""English Forge service — sessions, R2 upload, ASR, coach eval."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, HTTPException, status

from . import store
from .evaluator import EVALUATOR_VERSION, english_forge_eval_stub, evaluate_coach
from .prompts import default_prompt, get_prompt, list_prompts
from .schemas import (
    CoachCard,
    ConfirmResponseRequest,
    CreateResponseSessionRequest,
    CreateSessionRequest,
    EvaluateRequest,
    EvaluateResponse,
    FeedbackPublic,
    GradeBand,
    PendingStatus,
    ResponsePublic,
    ResponseSessionPublic,
    SessionPublic,
    SpeakPrompt,
)

logger = logging.getLogger(__name__)

UPLOAD_EXPIRY_SEC = 900
MAX_UPLOAD_BYTES = 25_000_000


def list_prompts_for_band(grade_band: GradeBand) -> list[SpeakPrompt]:
    return list_prompts(grade_band)


def get_prompt_or_404(prompt_id: str) -> SpeakPrompt:
    prompt = get_prompt(prompt_id)
    if not prompt:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Prompt not found")
    return prompt


def create_session(body: CreateSessionRequest) -> SessionPublic:
    prompt = (
        get_prompt(body.prompt_id)
        if body.prompt_id
        else default_prompt(body.grade_band)
    )
    if prompt is None or prompt.grade_band != body.grade_band:
        # Allow cross-lookup by id; otherwise default for band.
        prompt = default_prompt(body.grade_band)
        if body.prompt_id:
            found = get_prompt(body.prompt_id)
            if found:
                prompt = found

    row = store.create_session(
        {
            "grade_band": prompt.grade_band,
            "prompt_id": prompt.id,
            "prompt_title": prompt.title,
            "prompt_text": prompt.prompt,
            "listen_hint": prompt.listen_hint,
            "target_duration_sec": prompt.target_duration_sec,
            "max_duration_sec": prompt.max_duration_sec,
            "status": "active",
            "guest_key": body.guest_key,
        }
    )
    return _session_public(row)


def create_response_session(
    session_id: UUID,
    body: CreateResponseSessionRequest,
) -> ResponseSessionPublic:
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found")
    if str(session.get("status")) not in ("active", "finalized"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Session cannot accept audio")

    max_sec = int(session.get("max_duration_sec") or 60)
    if body.duration_sec > max_sec:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"message": "Recording too long", "max_duration_sec": max_sec},
        )
    if body.size_bytes > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Recording too large")

    content_type = (body.content_type or "audio/webm").split(";", 1)[0].strip().lower()
    if content_type not in ("audio/webm", "audio/wav", "audio/mpeg", "audio/mp4", "audio/ogg"):
        content_type = "audio/webm"

    response_id = uuid4()
    idempotency_key = body.idempotency_key or uuid4().hex
    expires_at = datetime.now(UTC) + timedelta(seconds=UPLOAD_EXPIRY_SEC)
    ext = "webm" if "webm" in content_type else "wav"
    audio_key = f"english-forge/{session_id}/responses/{response_id}.{ext}"

    store.create_response(
        {
            "id": str(response_id),
            "session_id": str(session_id),
            "audio_key": audio_key,
            "content_type": content_type,
            "duration_sec": body.duration_sec,
            "size_bytes": body.size_bytes,
            "idempotency_key": idempotency_key,
            "status": "pending_upload",
            "upload_expires_at": expires_at.isoformat(),
            "transcription_status": "not_queued",
        }
    )

    # Always try R2 — ENGLISH_FORGE_EVAL_STUB only stubs the coach LLM, not ASR.
    upload_url = ""
    stub_upload = False
    try:
        from app.storage.r2 import ensure_browser_put_cors, generate_presigned_put_url

        try:
            ensure_browser_put_cors()
        except Exception as cors_exc:  # noqa: BLE001
            logger.warning("EF R2 CORS ensure failed (continuing): %s", cors_exc)

        upload_url = generate_presigned_put_url(
            audio_key,
            content_type=content_type,
            expiry=UPLOAD_EXPIRY_SEC,
            content_length=body.size_bytes,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("EF presign failed, stub upload (no live ASR): %s", exc)
        stub_upload = True

    return ResponseSessionPublic(
        response_id=response_id,
        upload_url=upload_url,
        expires_at=expires_at,
        idempotency_key=idempotency_key,
        stub_upload=stub_upload or not upload_url,
    )


def upload_response_audio(
    session_id: UUID,
    response_id: UUID,
    *,
    audio_bytes: bytes,
    content_type: str | None,
    idempotency_key: str,
    duration_sec: int,
    background_tasks: BackgroundTasks | None = None,
) -> ResponsePublic:
    """Upload audio via API credentials (no browser→R2 CORS)."""
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found")
    row = store.get_response(response_id)
    if not row or str(row.get("session_id")) != str(session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Response not found")
    if idempotency_key != str(row.get("idempotency_key") or ""):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Idempotency key mismatch")
    if duration_sec != int(row["duration_sec"]):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Duration mismatch")
    if len(audio_bytes) < 500:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Recording is empty")
    if len(audio_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Recording too large")

    normalized = (content_type or str(row.get("content_type") or "audio/webm")).split(";", 1)[
        0
    ].strip().lower()
    if normalized not in ("audio/webm", "audio/wav", "audio/mpeg", "audio/mp4", "audio/ogg"):
        normalized = "audio/webm"

    try:
        from app.storage.r2 import upload_object

        upload_object(
            key=str(row["audio_key"]),
            body=audio_bytes,
            content_type=normalized,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("EF server upload failed: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not store recording",
        ) from exc

    store.update_response(
        response_id,
        {
            "size_bytes": len(audio_bytes),
            "content_type": normalized,
        },
    )
    return confirm_response(
        session_id,
        response_id,
        ConfirmResponseRequest(idempotency_key=idempotency_key, duration_sec=duration_sec),
        background_tasks=background_tasks,
    )


def confirm_response(
    session_id: UUID,
    response_id: UUID,
    body: ConfirmResponseRequest,
    background_tasks: BackgroundTasks | None = None,
) -> ResponsePublic:
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found")
    row = store.get_response(response_id)
    if not row or str(row.get("session_id")) != str(session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Response not found")
    if body.idempotency_key != str(row.get("idempotency_key") or ""):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Idempotency key mismatch")
    if body.duration_sec != int(row["duration_sec"]):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Duration mismatch")

    if str(row.get("status")) != "confirmed":
        # Always require the uploaded object when possible — Whisper needs real audio.
        try:
            from app.storage.r2 import object_head

            head = object_head(str(row["audio_key"]), raise_errors=False)
        except Exception as exc:  # noqa: BLE001
            head = None
            logger.warning("EF object_head failed: %s", exc)

        if head is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Uploaded audio not found. Please record again.",
            )
        stored = int(row["size_bytes"])
        actual = int(head["size"])
        if stored > 0 and abs(actual - stored) / max(stored, 1) > 0.35:
            logger.warning(
                "EF size mismatch stored=%s actual=%s — continuing",
                stored,
                actual,
            )

        row = store.update_response(
            response_id,
            {
                "status": "confirmed",
                "confirmed_at": datetime.now(UTC).isoformat(),
                "transcription_status": "queued",
                "size_bytes": actual,
            },
        ) or row

    store.upsert_evaluation(
        session_id,
        {"status": "pending", "response_id": str(response_id)},
    )

    if background_tasks is not None:
        background_tasks.add_task(process_response_pipeline, str(response_id))
    else:
        process_response_pipeline(str(response_id))

    return ResponsePublic(
        id=UUID(str(row["id"])),
        session_id=session_id,
        status=str(row.get("status") or "confirmed"),
        duration_sec=int(row["duration_sec"]),
        transcription_status=str(row.get("transcription_status") or "queued"),
    )


def finalize_session(
    session_id: UUID,
    background_tasks: BackgroundTasks | None = None,
) -> PendingStatus:
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found")
    store.update_session(session_id, {"status": "finalized"})
    response = store.get_latest_response(session_id)
    if response and str(response.get("transcription_status")) in (
        "not_queued",
        "queued",
        "failed",
    ):
        if background_tasks is not None:
            background_tasks.add_task(process_response_pipeline, str(response["id"]))
        else:
            process_response_pipeline(str(response["id"]))
    return get_pending(session_id)


def get_pending(session_id: UUID) -> PendingStatus:
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found")
    response = store.get_latest_response(session_id)
    evaluation = store.get_evaluation(session_id)

    transcription_status = str((response or {}).get("transcription_status") or "not_queued")
    evaluation_status = str((evaluation or {}).get("status") or "pending")
    ready = evaluation_status in ("completed", "stubbed") and bool(
        (evaluation or {}).get("coach_card")
    )

    if ready:
        message = "Your coach feedback is ready."
    elif transcription_status in ("queued", "processing"):
        message = "Listening to your recording…"
    elif evaluation_status in ("pending", "processing"):
        message = "Preparing your feedback…"
    elif evaluation_status == "failed" or transcription_status == "failed":
        message = "Something went wrong. Please try again."
    else:
        message = "Waiting for your recording…"

    # Opportunistic retry if stuck
    if (
        response
        and not ready
        and transcription_status in ("queued", "failed")
        and str(response.get("status")) == "confirmed"
    ):
        process_response_pipeline(str(response["id"]))

    return PendingStatus(
        session_id=session_id,
        status=str(session.get("status") or "active"),
        transcription_status=transcription_status,
        evaluation_status=evaluation_status,
        ready=ready,
        message=message,
    )


def get_feedback(session_id: UUID) -> FeedbackPublic:
    pending = get_pending(session_id)
    if not pending.ready:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Feedback not ready yet")
    evaluation = store.get_evaluation(session_id) or {}
    response = store.get_latest_response(session_id) or {}
    card_data = evaluation.get("coach_card") or {}
    card = CoachCard.model_validate(card_data)
    return FeedbackPublic(
        session_id=session_id,
        transcript=str(response.get("transcript") or ""),
        coach_card=card,
        evaluation_status=str(evaluation.get("status") or "completed"),
    )


def evaluate_direct(body: EvaluateRequest) -> EvaluateResponse:
    card = asyncio.run(evaluate_coach(body))
    return EvaluateResponse(transcript=body.transcript, coach_card=card)


def process_response_pipeline(response_id: str) -> None:
    """ASR then coach eval (sync worker for BackgroundTasks)."""
    try:
        asyncio.run(_process_response_async(response_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception("EF pipeline failed for %s: %s", response_id, exc)
        store.update_response(
            response_id,
            {"transcription_status": "failed", "transcription_error": str(exc)[:500]},
        )
        row = store.get_response(response_id)
        if row:
            store.upsert_evaluation(
                row["session_id"],
                {"status": "failed", "error": str(exc)[:500], "response_id": response_id},
            )


async def _process_response_async(response_id: str) -> None:
    row = store.get_response(response_id)
    if not row:
        return
    session = store.get_session(row["session_id"])
    if not session:
        return

    store.update_response(response_id, {"transcription_status": "processing"})
    store.upsert_evaluation(
        row["session_id"],
        {"status": "processing", "response_id": response_id},
    )

    stub_eval = english_forge_eval_stub()
    transcript = ""
    asr_status = "failed"

    # Prefer real Whisper ASR whenever audio exists. Never invent a polished
    # "practice" transcript that pretends to be the student's words.
    try:
        from app.speaking.providers.factory import get_asr_provider
        from app.storage.r2 import get_object_bytes, object_head

        head = object_head(str(row["audio_key"]), raise_errors=False)
        if head is not None and int(head.get("size") or 0) > 0:
            audio_bytes = get_object_bytes(key=str(row["audio_key"]))
            filename = str(row["audio_key"]).rsplit("/", 1)[-1]
            asr = get_asr_provider()
            logger.info(
                "English Forge ASR → %s (%s bytes)",
                getattr(asr, "name", type(asr).__name__),
                len(audio_bytes),
            )
            result = await asr.transcribe(audio_bytes=audio_bytes, filename=filename)
            transcript = str(result.get("text") or "").strip()
            # Ignore punctuation-only / empty Whisper noise
            meaningful = "".join(ch for ch in transcript if ch.isalnum())
            if not meaningful:
                transcript = ""
            asr_status = "completed"
            store.update_response(
                response_id,
                {"transcript": transcript, "transcription_status": asr_status},
            )
        else:
            logger.info("EF no audio object for %s — cannot ASR", response_id)
            store.update_response(
                response_id,
                {
                    "transcript": "",
                    "transcription_status": "stubbed",
                    "transcription_error": "no_audio_object",
                },
            )
            asr_status = "stubbed"
    except Exception as exc:  # noqa: BLE001
        logger.warning("EF ASR failed: %s", exc)
        store.update_response(
            response_id,
            {
                "transcript": "",
                "transcription_status": "failed" if not stub_eval else "stubbed",
                "transcription_error": str(exc)[:500],
            },
        )
        asr_status = "stubbed" if stub_eval else "failed"
        if not stub_eval:
            store.upsert_evaluation(
                row["session_id"],
                {"status": "failed", "error": f"asr:{exc}"[:500], "response_id": response_id},
            )
            return

    req = EvaluateRequest(
        grade_band=session["grade_band"],
        prompt=str(session.get("prompt_text") or ""),
        transcript=transcript or "(no speech heard)",
        duration_sec=float(row.get("duration_sec") or 0),
        locale_hint="en-IN",
        attempt_meta={"session_id": str(session["id"]), "prompt_id": session.get("prompt_id")},
    )
    try:
        card = await evaluate_coach(req)
        status_label = (
            "stubbed"
            if stub_eval
            or (
                card.internal_signals
                and str(getattr(card.internal_signals, "evaluator_version", "")).endswith(
                    "stub-v0"
                )
            )
            else "completed"
        )
        store.upsert_evaluation(
            row["session_id"],
            {
                "status": status_label,
                "coach_card": card.model_dump(),
                "evaluator_version": EVALUATOR_VERSION,
                "response_id": response_id,
                "error": None,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("EF coach eval failed: %s", exc)
        store.upsert_evaluation(
            row["session_id"],
            {"status": "failed", "error": str(exc)[:500], "response_id": response_id},
        )


def _session_public(row: dict[str, Any]) -> SessionPublic:
    prompt_id = str(row["prompt_id"])
    pack = get_prompt(prompt_id)
    prompt = SpeakPrompt(
        id=prompt_id,
        grade_band=row["grade_band"],
        title=str(row["prompt_title"]),
        prompt=str(row["prompt_text"]),
        listen_hint=row.get("listen_hint"),
        target_duration_sec=int(row.get("target_duration_sec") or 45),
        max_duration_sec=int(row.get("max_duration_sec") or 60),
        reference_transcript=(
            pack.reference_transcript if pack else None
        ),
        is_anchor=bool(pack.is_anchor) if pack else False,
        skills=list(pack.skills) if pack else [],
        difficulty=pack.difficulty if pack else None,
    )
    return SessionPublic(
        id=UUID(str(row["id"])),
        grade_band=row["grade_band"],
        prompt=prompt,
        status=str(row.get("status") or "active"),
        created_at=row.get("created_at") or datetime.now(UTC),
    )
