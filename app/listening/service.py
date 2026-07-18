"""Business logic for the Listening module.

Routes stay thin; this layer enforces ownership, presigns audio,
calls the synchronous evaluator, and persists module_scores.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import HTTPException, status

from app.cache.hybrid_cache import delete_many, get_json, invalidate_prefix, set_json
from app.cache.mock_cache import read_unlock_snapshot
from app.db.module_submit_bundle import persist_module_submit_bundle
from app.config import get_settings
from app.listening import repository as repo
from app.listening.constants import (
    LISTENING_AUDIO_PRESIGN_EXPIRY_SECONDS,
    LISTENING_DURATION_MINUTES,
    LISTENING_GRACE_SECONDS,
)
from app.listening.evaluation import (
    build_skill_breakdown,
    calculate_band,
    is_answer_correct,
    score_answers,
)
from app.listening.explanations import build_explanation
from app.listening.practice_tip import build_practice_tip
from app.listening.schemas import (
    AutosaveResponse,
    ListeningPart,
    ListeningQuestion,
    ListeningQuestionsResponse,
    ListeningScoreReport,
    NotesSection,
    QuestionReviewItem,
    SkillBreakdownEntry,
    StartListeningResponse,
    SubmitListeningResponse,
)
from app.schemas.test_engine import TestSummary
from app.listening.instructions import (
    extract_form_title,
    extract_listening_instructions,
    extract_notes_layout,
)
from app.listening.timing import ListeningStartTiming, ListeningSubmitTiming, _PhaseTimer
from app.mock_catalog.constants import M01_MOCK_TEST_ID, M02_MOCK_TEST_ID
from app.services.mock_progress_timing import MockProgressTiming
from app.storage.r2 import generate_signed_url, get_object_stream, object_exists, object_head, parse_r2_object_url


DEFAULT_PART_META: dict[int, dict[str, str]] = {
    1: {
        "title": "Part 1 — Social Dialogue",
        "context": "Everyday social conversation between two speakers.",
        "common_question_type": "form_completion",
    },
    2: {
        "title": "Part 2 — Social Monologue",
        "context": "One speaker in an everyday social setting (tour, broadcast, briefing).",
        "common_question_type": "mcq / map_labeling",
    },
    3: {
        "title": "Part 3 — Academic Seminar",
        "context": "Academic discussion involving two to four speakers.",
        "common_question_type": "mcq / matching",
    },
    4: {
        "title": "Part 4 — Academic Lecture",
        "context": "Single speaker delivering a university-level lecture.",
        "common_question_type": "note_completion",
    },
}

M01_PART_META: dict[int, dict[str, str]] = {
    1: {
        "title": "Part 1",
        "context": "Greenfield College",
        "common_question_type": "form_completion",
    },
    2: {
        "title": "Part 2",
        "context": "Leisure Centre Orientation",
        "common_question_type": "mcq / matching",
    },
    3: {
        "title": "Part 3",
        "context": "Tutorial Discussion",
        "common_question_type": "mcq / sentence_completion",
    },
    4: {
        "title": "Part 4",
        "context": "Public Transit & CO2",
        "common_question_type": "note_completion",
    },
}

M02_PART_META: dict[int, dict[str, str]] = {
    1: {
        "title": "Part 1",
        "context": "Telephone Enquiry to a Letting Agency — Tenant Registration",
        "common_question_type": "form_completion",
    },
    2: {
        "title": "Part 2",
        "context": "Welcome Talk to Visitors at a Wetlands Nature Reserve",
        "common_question_type": "sentence_completion · mcq",
    },
    3: {
        "title": "Part 3",
        "context": "Tutorial Discussion — Students Reviewing a Research Project",
        "common_question_type": "mcq · sentence_completion",
    },
    4: {
        "title": "Part 4",
        "context": "Academic Lecture — Dendrochronology (Archaeology)",
        "common_question_type": "note_completion",
    },
}

# Keep legacy name for any external imports.
PART_META = DEFAULT_PART_META


def _part_meta_for_mock(mock_test_id: UUID | str, part_num: int) -> dict[str, str]:
    mid = str(mock_test_id)
    if mid == M01_MOCK_TEST_ID:
        table = M01_PART_META
    elif mid == M02_MOCK_TEST_ID:
        table = M02_PART_META
    else:
        table = DEFAULT_PART_META
    return table.get(part_num, DEFAULT_PART_META.get(part_num, {}))


def _is_dev() -> bool:
    return get_settings().app_env.strip().lower() == "development"


def _audio_key_candidates(stored: str) -> list[str]:
    key = parse_r2_object_url(stored.strip()) or stored.strip().lstrip("/")
    candidates = [key]
    if key.startswith("listening/m01/"):
        candidates.append(key.replace("listening/m01/", "listening/greenfield/", 1))
    deduped: list[str] = []
    for c in candidates:
        if c not in deduped:
            deduped.append(c)
    return deduped


def invalidate_listening_audio_caches(*, mock_test_id: UUID | str) -> None:
    """Drop cached question payloads and presigned URLs after admin audio upload."""
    mid = str(mock_test_id)
    delete_many([f"listening_questions:{mid}:{p}" for p in range(0, 5)])
    invalidate_prefix(f"r2_presign:listening/{mid}/")


def _audio_storage_key(stored: str | None) -> str | None:
    if not stored or not stored.strip():
        return None
    return _audio_key_candidates(stored)[0]


def _listening_playback_url(
    *,
    mock_test_id: UUID,
    part: int,
    attempt_id: UUID,
) -> str:
    """Same-origin URL for HTML5 audio (proxied via Next.js with auth cookies)."""
    params = urlencode({"part": str(part), "attempt_id": str(attempt_id)})
    return f"/api/listening/{mock_test_id}/part-audio?{params}"


def _apply_playback_urls(
    response: ListeningQuestionsResponse,
    *,
    mock_test_id: UUID,
    attempt_id: UUID,
) -> ListeningQuestionsResponse:
    parts: list[ListeningPart] = []
    for part in response.parts:
        playback = _listening_playback_url(
            mock_test_id=mock_test_id,
            part=int(part.part),
            attempt_id=attempt_id,
        )
        questions = [
            question.model_copy(update={"audio_url": playback})
            for question in part.questions
        ]
        parts.append(part.model_copy(update={"questions": questions}))
    return response.model_copy(update={"parts": parts})


def _presign_questions_response(
    response: ListeningQuestionsResponse,
) -> ListeningQuestionsResponse:
    """Always mint fresh presigned URLs (never serve stale signed URLs from cache)."""
    presigned_by_key: dict[str, str | None] = {}
    parts: list[ListeningPart] = []
    for part in response.parts:
        questions: list[ListeningQuestion] = []
        for question in part.questions:
            storage_key = _audio_storage_key(question.audio_url)
            if storage_key:
                if storage_key not in presigned_by_key:
                    presigned_by_key[storage_key] = _presign_audio(storage_key)
                signed = presigned_by_key[storage_key]
            else:
                signed = None
            questions.append(question.model_copy(update={"audio_url": signed}))
        parts.append(part.model_copy(update={"questions": questions}))
    return response.model_copy(update={"parts": parts})


def _presign_audio(stored: str | None) -> str | None:
    if not stored or not stored.strip():
        return None
    keys = _audio_key_candidates(stored)
    cache_key = f"r2_presign:{keys[0]}"
    cached = get_json(cache_key)
    if isinstance(cached, str) and cached:
        return cached

    resolved: str | None = None
    for key in keys:
        if object_exists(key):
            resolved = key
            break
    if resolved is None:
        resolved = keys[0]
    try:
        url = generate_signed_url(
            resolved,
            expiry=LISTENING_AUDIO_PRESIGN_EXPIRY_SECONDS,
        )
        set_json(cache_key, url, ttl_seconds=2700)
        return url
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Listening audio is not available: {exc}",
        ) from exc


def _ensure_owner(attempt: dict[str, Any], user_id: UUID) -> None:
    from app.security.ownership import ensure_owner_or_not_found

    ensure_owner_or_not_found(attempt, user_id)


def _listening_duration_seconds(
    *, mock_test_id: UUID, mock_attempt_id: UUID | None
) -> int:
    if mock_attempt_id is not None:
        from app.services import mock_orchestrator_repository as mock_repo

        minutes = mock_repo.module_duration_minutes(
            mock_test_id=mock_test_id, module="listening"
        )
        if minutes:
            return minutes * 60
    return LISTENING_DURATION_MINUTES * 60


def _listening_duration_minutes(
    *, mock_test_id: UUID, mock_attempt_id: UUID | None
) -> int:
    return _listening_duration_seconds(
        mock_test_id=mock_test_id, mock_attempt_id=mock_attempt_id
    ) // 60


def _parse_started_at(attempt: dict[str, Any]) -> datetime:
    raw = attempt.get("started_at")
    if isinstance(raw, str):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if isinstance(raw, datetime):
        return raw
    return datetime.now(UTC)


def _mock_listening_session_started_at(
    *,
    user_id: UUID,
    mock_test_id: UUID,
    mock_attempt_id: UUID,
    current_attempt: dict[str, Any],
) -> datetime:
    """One clock for all listening parts within a mock attempt."""
    earliest = repo.earliest_listening_started_at(
        user_id=user_id,
        mock_test_id=mock_test_id,
        mock_attempt_id=mock_attempt_id,
    )
    if earliest and earliest.get("started_at"):
        return _parse_started_at(earliest)
    return _parse_started_at(current_attempt)


def schedule_stale_listening_cleanup(
    *,
    user_id: UUID,
    mock_test_id: UUID,
    mock_attempt_id: UUID,
    part: int,
) -> None:
    """Fire-and-forget hygiene: abandon orphan/superseded in_progress listening rows."""
    repo.abandon_stale_listening_attempts(
        user_id=user_id,
        mock_test_id=mock_test_id,
        mock_attempt_id=mock_attempt_id,
        part=part,
    )


def start_attempt(
    *,
    mock_test_id: UUID,
    user_id: UUID,
    force_new: bool = False,
    part: int = 1,
    mock_attempt_id: UUID | None = None,
    include_questions: bool = False,
    timing: ListeningStartTiming | None = None,
) -> StartListeningResponse:
    """Create a new listening attempt, or resume the user's existing in-progress one."""
    t_request = perf_counter()
    t0 = perf_counter()
    test_row = repo.get_mock_test(mock_test_id, allow_unpublished=_is_dev())
    if mock_attempt_id is not None:
        from app.services import mock_orchestrator

        if timing is not None:
            timing.unlock_source = (
                "cache"
                if read_unlock_snapshot(
                    mock_attempt_id=mock_attempt_id, user_id=user_id
                )
                else "db"
            )
        t_unlock = perf_counter()
        mock_orchestrator.assert_module_unlocked(
            mock_attempt_id=mock_attempt_id,
            user_id=user_id,
            mock_test_id=mock_test_id,
            module="listening",
            part=part,
        )
        if timing is not None:
            timing.unlock_ms = round((perf_counter() - t_unlock) * 1000)
    t_attempt = perf_counter()
    existing = repo.find_in_progress_listening_attempt(
        user_id=user_id,
        mock_test_id=mock_test_id,
        part=part,
        mock_attempt_id=mock_attempt_id,
    )
    if existing and force_new:
        repo.abandon_listening_attempt(attempt_id=UUID(str(existing["id"])))
        existing = None

    if existing:
        existing_ma = existing.get("mock_attempt_id")
        existing_mock_attempt_id = (
            UUID(str(existing_ma)) if existing_ma else mock_attempt_id
        )
        started_at = (
            _mock_listening_session_started_at(
                user_id=user_id,
                mock_test_id=mock_test_id,
                mock_attempt_id=existing_mock_attempt_id,
                current_attempt=existing,
            )
            if existing_mock_attempt_id is not None
            else _parse_started_at(existing)
        )
        response = StartListeningResponse(
            attempt_id=UUID(str(existing["id"])),
            started_at=started_at,
            server_time=datetime.now(UTC),
            status=str(existing.get("status", "in_progress")),
            duration_seconds=_listening_duration_seconds(
                mock_test_id=mock_test_id,
                mock_attempt_id=existing_mock_attempt_id,
            ),
            resumed=True,
        )
        if timing is not None:
            timing.attempt_ms = round((perf_counter() - t_attempt) * 1000)
        if include_questions:
            q = get_session_questions(
                mock_test_id=mock_test_id,
                user_id=user_id,
                part=part,
                test_row=test_row,
                attempt=existing,
                timing=timing,
            )
            response.test = q.test
            response.parts = q.parts
            response.duration_seconds = q.duration_seconds
        if timing is not None:
            timing.duration_ms = round((perf_counter() - t_request) * 1000)
        return response

    row = repo.insert_listening_attempt(
        user_id=user_id,
        mock_test_id=mock_test_id,
        mock_attempt_id=mock_attempt_id,
        part=part,
    )
    started_at = (
        _mock_listening_session_started_at(
            user_id=user_id,
            mock_test_id=mock_test_id,
            mock_attempt_id=mock_attempt_id,
            current_attempt=row,
        )
        if mock_attempt_id is not None
        else _parse_started_at(row)
    )
    response = StartListeningResponse(
        attempt_id=UUID(str(row["id"])),
        started_at=started_at,
        server_time=datetime.now(UTC),
        status=str(row.get("status", "in_progress")),
        duration_seconds=_listening_duration_seconds(
            mock_test_id=mock_test_id, mock_attempt_id=mock_attempt_id
        ),
        resumed=False,
    )
    if timing is not None:
        timing.attempt_ms = round((perf_counter() - t_attempt) * 1000)
    if include_questions:
        q = get_session_questions(
            mock_test_id=mock_test_id,
            user_id=user_id,
            part=part,
            test_row=test_row,
            attempt=row,
            timing=timing,
        )
        response.test = q.test
        response.parts = q.parts
        response.duration_seconds = q.duration_seconds
    if timing is not None:
        timing.duration_ms = round((perf_counter() - t_request) * 1000)
    return response


def stream_part_audio(
    *,
    mock_test_id: UUID,
    user_id: UUID,
    attempt_id: UUID,
    part: int,
    range_header: str | None,
) -> tuple[Any, dict[str, str], int]:
    """Authenticated R2 audio stream for an in-progress listening attempt."""
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if str(attempt.get("mock_test_id")) != str(mock_test_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attempt does not belong to this mock test.",
        )
    if str(attempt.get("module")) != "listening":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attempt is not a listening attempt.",
        )
    if str(attempt.get("status")) not in {"in_progress", "started"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Listening audio is only available during an active attempt.",
        )
    attempt_part = attempt.get("part")
    if attempt_part is not None and int(attempt_part) != part:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Part does not match this listening attempt.",
        )

    rows = repo.list_questions_public(mock_test_id, part=part)
    storage_key: str | None = None
    for row in rows:
        raw = row.get("audio_url")
        if raw:
            storage_key = _audio_storage_key(str(raw))
            break
    if not storage_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No listening audio configured for this part.",
        )
    if not object_head(storage_key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audio not found in R2 at key: {storage_key}",
        )
    try:
        return get_object_stream(storage_key, range_header=range_header)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


def get_session_questions(
    *,
    mock_test_id: UUID,
    user_id: UUID,
    part: int | None = None,
    test_row: dict[str, Any] | None = None,
    attempt: dict[str, Any] | None = None,
    timing: ListeningStartTiming | None = None,
) -> ListeningQuestionsResponse:
    if attempt is None:
        in_progress = repo.find_in_progress_listening_attempt(
            user_id=user_id,
            mock_test_id=mock_test_id,
            part=part,
        )
        if not in_progress:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Start a listening attempt before loading questions and audio.",
            )
        attempt = in_progress

    attempt_id = UUID(str(attempt["id"]))
    cache_key = f"listening_questions:{mock_test_id}:{part or 0}"
    t_questions = perf_counter()
    cached = get_json(cache_key)
    if isinstance(cached, dict):
        try:
            payload = ListeningQuestionsResponse.model_validate(cached)
            if timing is not None:
                timing.questions_source = "cache"
                timing.questions_ms = round((perf_counter() - t_questions) * 1000)
            return _apply_playback_urls(
                payload,
                mock_test_id=mock_test_id,
                attempt_id=attempt_id,
            )
        except Exception:
            pass

    if timing is not None:
        timing.questions_source = "db"
    presign_timer = _PhaseTimer()

    if test_row is None:
        test_row = repo.get_mock_test(mock_test_id, allow_unpublished=_is_dev())
    t0 = perf_counter()
    rows = repo.list_questions_public(mock_test_id, part=part)
    fetch_ms = round((perf_counter() - t0) * 1000)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No listening questions found for this mock test.",
        )

    t0 = perf_counter()
    display_offsets = repo.part_display_offsets(mock_test_id=mock_test_id)
    offsets_ms = round((perf_counter() - t0) * 1000)

    t_build = perf_counter()
    grouped: dict[int, list[ListeningQuestion]] = {1: [], 2: [], 3: [], 4: []}
    for row in rows:
        part_raw = row.get("part")
        part = int(part_raw) if part_raw is not None else 1
        if part not in grouped:
            grouped[part] = []
        raw_audio = row.get("audio_url")
        qn = int(row["question_number"])
        instructions: str | None = None
        if qn == 1 or row.get("passage_text"):
            instructions = extract_listening_instructions(row.get("passage_text"))
        grouped[part].append(
            ListeningQuestion(
                id=UUID(str(row["id"])),
                part=part,  # type: ignore[arg-type]
                question_number=qn,
                display_number=display_offsets.get(part, 0) + qn,
                question_type=str(row["question_type"]),
                prompt=str(row["prompt"]),
                instructions=instructions,
                options=row.get("options"),
                skill_tag=row.get("skill_tag"),
                audio_url=str(raw_audio).strip() if raw_audio else None,
            )
        )

    parts: list[ListeningPart] = []
    for part_num in sorted(grouped.keys()):
        items = grouped[part_num]
        if not items:
            continue
        meta = _part_meta_for_mock(mock_test_id, part_num)
        passage_for_meta: str | None = None
        for row in rows:
            if int(row.get("part") or 1) != part_num:
                continue
            if row.get("passage_text"):
                passage_for_meta = row.get("passage_text")
                break
        notes_layout = extract_notes_layout(passage_for_meta)
        notes_sections_raw = notes_layout.get("notes_sections")
        notes_sections = (
            [NotesSection(**s) for s in notes_sections_raw]
            if notes_sections_raw
            else None
        )
        parts.append(
            ListeningPart(
                part=part_num,  # type: ignore[arg-type]
                title=meta.get("title", f"Part {part_num}"),
                context=meta.get("context", ""),
                common_question_type=meta.get("common_question_type", ""),
                questions=items,
                form_title=extract_form_title(passage_for_meta),
                notes_title=notes_layout.get("notes_title"),
                notes_sections=notes_sections,
            )
        )

    mock_attempt_raw = attempt.get("mock_attempt_id")
    mock_attempt_id = UUID(str(mock_attempt_raw)) if mock_attempt_raw else None

    response = ListeningQuestionsResponse(
        test=TestSummary(
            id=UUID(str(test_row["id"])),
            title=str(test_row["title"]),
            description=test_row.get("description"),
        ),
        parts=parts,
        duration_seconds=_listening_duration_seconds(
            mock_test_id=mock_test_id, mock_attempt_id=mock_attempt_id
        ),
    )
    set_json(cache_key, response.model_dump(mode="json"), ttl_seconds=600)
    t_presign = perf_counter()
    signed_response = _apply_playback_urls(
        response,
        mock_test_id=mock_test_id,
        attempt_id=attempt_id,
    )
    presign_timer.add(t_presign)
    build_ms = round((perf_counter() - t_build) * 1000)
    if timing is not None:
        timing.audio_presign_ms = presign_timer.total_ms
        timing.questions_ms = fetch_ms + offsets_ms + build_ms
    return signed_response


def autosave_answer(
    *,
    attempt_id: UUID,
    user_id: UUID,
    question_id: UUID,
    user_answer: str,
) -> AutosaveResponse:
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "listening":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attempt is not a listening attempt.",
        )
    if attempt.get("status") != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Attempt cannot be edited (status={attempt.get('status')}).",
        )
    if not repo.question_belongs_to(UUID(str(attempt["mock_test_id"])), question_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question does not belong to this listening attempt.",
        )
    repo.upsert_answer(
        attempt_id=attempt_id,
        question_id=question_id,
        user_answer=user_answer,
    )
    return AutosaveResponse(
        ok=True,
        question_id=question_id,
        saved_at=datetime.now(UTC),
    )


def _to_breakdown_entries(
    raw: dict[str, dict[str, float | int]],
) -> dict[str, SkillBreakdownEntry]:
    return {
        skill: SkillBreakdownEntry(
            correct=int(v.get("correct", 0)),
            total=int(v.get("total", 0)),
            pct=float(v.get("pct", 0.0)),
        )
        for skill, v in raw.items()
    }


def submit_attempt(
    *,
    attempt_id: UUID,
    user_id: UUID,
    answers: list[dict[str, str]],
    timing: ListeningSubmitTiming | None = None,
) -> SubmitListeningResponse:
    t_request = perf_counter()
    t0 = perf_counter()
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if timing is not None:
        timing.attempt_ms = round((perf_counter() - t0) * 1000)
    if attempt.get("module") != "listening":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attempt is not a listening attempt.",
        )
    if attempt.get("status") != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Attempt cannot be submitted (status={attempt.get('status')}).",
        )

    mock_test_id = UUID(str(attempt["mock_test_id"]))
    attempt_part = attempt.get("part")
    part = int(attempt_part) if attempt_part is not None else None
    t0 = perf_counter()
    questions = repo.list_questions_for_scoring(mock_test_id, part=part)
    if timing is not None:
        timing.scoring_query_ms = round((perf_counter() - t0) * 1000)
    if not questions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No listening questions are configured for this mock test.",
        )

    answers_by_qid: dict[str, str] = {}
    for item in answers:
        qid = str(item.get("question_id", "")).strip()
        if not qid:
            continue
        answers_by_qid[qid] = str(item.get("user_answer", "")).strip()

    valid_ids = {str(q["id"]) for q in questions}
    unknown = [qid for qid in answers_by_qid if qid not in valid_ids]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more question_ids are invalid for this attempt.",
        )

    t0 = perf_counter()
    raw_score, total, scored_rows = score_answers(
        questions=questions,
        answers_by_qid=answers_by_qid,
    )
    if timing is not None:
        timing.scoring_compute_ms = round((perf_counter() - t0) * 1000)

    now = datetime.now(UTC)
    mock_attempt_raw = attempt.get("mock_attempt_id")
    mock_attempt_id = UUID(str(mock_attempt_raw)) if mock_attempt_raw else None
    started_at = (
        _mock_listening_session_started_at(
            user_id=user_id,
            mock_test_id=mock_test_id,
            mock_attempt_id=mock_attempt_id,
            current_attempt=attempt,
        )
        if mock_attempt_id is not None
        else _parse_started_at(attempt)
    )
    grace = timedelta(seconds=LISTENING_GRACE_SECONDS)
    duration_min = _listening_duration_minutes(
        mock_test_id=mock_test_id, mock_attempt_id=mock_attempt_id
    )
    late = now - started_at > timedelta(minutes=duration_min) + grace

    band = calculate_band(raw_score, total=total)
    breakdown = build_skill_breakdown(questions=questions, rows=scored_rows)

    t0 = perf_counter()
    completed = persist_module_submit_bundle(
        attempt_id=attempt_id,
        user_id=user_id,
        module="listening",
        completed_at=now,
        answer_rows=scored_rows,
        raw_score=raw_score,
        total_count=total,
        band=band,
        skill_breakdown=breakdown,
    )
    if timing is not None:
        timing.rpc_bundle_ms = round((perf_counter() - t0) * 1000)

    try:
        from app.learning.service import schedule_profile_refresh

        schedule_profile_refresh(user_id)
    except Exception:
        pass

    completed_raw = completed.get("completed_at") or now.isoformat()
    submitted_at = (
        datetime.fromisoformat(completed_raw.replace("Z", "+00:00"))
        if isinstance(completed_raw, str)
        else completed_raw
    )

    mock_next_part: int | None = None
    mock_listening_complete = False
    if attempt.get("mock_attempt_id"):
        from app.services import mock_orchestrator

        progress_timing = MockProgressTiming() if timing is not None else None
        if timing is not None:
            timing.progress_timing = progress_timing
        progress = mock_orchestrator.on_module_attempt_completed(
            test_attempt_id=attempt_id,
            user_id=user_id,
            attempt=completed,
            timing=progress_timing,
        )
        if timing is not None and progress_timing is not None:
            timing.progress_ms = progress_timing.progress_ms
        if progress is not None:
            if progress.status == "completed" or progress.next_module != "listening":
                mock_listening_complete = True
            elif progress.next_module == "listening":
                mock_next_part = progress.next_part

    response = SubmitListeningResponse(
        attempt_id=attempt_id,
        status="completed",
        submitted_at=submitted_at,
        raw_score=raw_score,
        total_questions=total,
        band=band,
        late_submission=late,
        skill_breakdown=_to_breakdown_entries(breakdown),
        mock_next_part=mock_next_part,
        mock_listening_complete=mock_listening_complete,
    )
    if timing is not None:
        timing.duration_ms = round((perf_counter() - t_request) * 1000)
    return response


def get_score_report(
    *,
    attempt_id: UUID,
    user_id: UUID,
) -> ListeningScoreReport:
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "listening":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attempt is not a listening attempt.",
        )
    if attempt.get("status") != "completed":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Score report is not available yet.",
        )
    score = repo.get_module_score(attempt_id)
    if not score:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Score report not found.",
        )

    started_at = _parse_started_at(attempt)
    mock_test_id = UUID(str(attempt["mock_test_id"]))
    mock_attempt_raw = attempt.get("mock_attempt_id")
    mock_attempt_id = UUID(str(mock_attempt_raw)) if mock_attempt_raw else None
    duration_min = _listening_duration_minutes(
        mock_test_id=mock_test_id, mock_attempt_id=mock_attempt_id
    )
    completed_raw = attempt.get("completed_at")
    submitted_at = None
    late = False
    if isinstance(completed_raw, str) and completed_raw:
        submitted_at = datetime.fromisoformat(completed_raw.replace("Z", "+00:00"))
        late = submitted_at - started_at > timedelta(
            minutes=duration_min,
            seconds=LISTENING_GRACE_SECONDS,
        )

    raw_breakdown = score.get("skill_breakdown") or {}
    breakdown: dict[str, SkillBreakdownEntry] = {}
    for skill, v in raw_breakdown.items():
        if not isinstance(v, dict):
            continue
        breakdown[str(skill)] = SkillBreakdownEntry(
            correct=int(v.get("correct", 0)),
            total=int(v.get("total", 0)),
            pct=float(v.get("pct", 0.0)),
        )

    mock_test_id = UUID(str(attempt["mock_test_id"]))
    test_row = repo.get_mock_test(mock_test_id, allow_unpublished=_is_dev())
    answer_rows = repo.list_answers_for_attempt(attempt_id)
    answers_by_qid = {
        str(row["question_id"]): {
            "user_answer": str(row.get("user_answer") or ""),
            "is_correct": row.get("is_correct"),
        }
        for row in answer_rows
    }

    attempt_part = attempt.get("part")
    review_part = int(attempt_part) if attempt_part is not None else None
    review_items: list[QuestionReviewItem] = []
    for q in repo.list_questions_for_review(mock_test_id, part=review_part):
        qid = str(q["id"])
        ans = answers_by_qid.get(qid, {})
        user_answer = ans.get("user_answer", "")
        stored_correct = q.get("is_correct")
        if stored_correct is None:
            correct_flag = is_answer_correct(user_answer, q.get("correct_answer"))
        else:
            correct_flag = bool(stored_correct)
        correct_display = str(q.get("correct_answer") or "—")
        review_items.append(
            QuestionReviewItem(
                question_id=UUID(qid),
                question_number=int(q["question_number"]),
                question_type=str(q.get("question_type") or ""),
                prompt=str(q.get("prompt") or ""),
                user_answer=user_answer,
                correct_answer=correct_display,
                is_correct=correct_flag,
                explanation=build_explanation(
                    prompt=str(q.get("prompt") or ""),
                    user_answer=user_answer,
                    correct_answer=q.get("correct_answer"),
                    is_correct=correct_flag,
                ),
            )
        )

    return ListeningScoreReport(
        attempt_id=attempt_id,
        status="completed",
        module="listening",
        test_title=str(test_row.get("title") or ""),
        submitted_at=submitted_at,
        raw_score=int(score.get("raw_score") or score.get("correct_count") or 0),
        total_questions=int(score.get("total_count") or 0),
        band=float(score.get("band") or 0.0),
        late_submission=late,
        skill_breakdown=breakdown,
        questions=review_items,
        practice_tip=build_practice_tip(breakdown),
    )
