"""Admin speaking builder — save/load Parts 1–3 prompts + optional R2 video keys."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.admin.audit import log_admin_action
from app.admin.schemas import (
    SpeakingBuilderQuestionIn,
    SpeakingBuilderQuestionOut,
    SpeakingBuilderSaveRequest,
    SpeakingBuilderSaveResponse,
    SpeakingPartResponse,
)
from app.db.supabase_client import get_supabase


def _assert_mock_exists(sb: Any, mock_id: str) -> None:
    row = (
        sb.table("mock_tests")
        .select("id")
        .eq("id", mock_id)
        .limit(1)
        .execute()
    ).data
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock test not found.")


def _default_question_type(part: int) -> str:
    return f"speaking_part{part}"


def _default_part_label(part: int) -> str:
    return f"Part {part}"


def _default_kind(part: int) -> str:
    return "part2_intro" if part == 2 else "question"


def _default_record_sec(part: int) -> int:
    if part == 2:
        return 120
    if part == 3:
        return 60
    return 45


def _signed_preview(video_key: str | None) -> str | None:
    if not video_key or not str(video_key).strip():
        return None
    key = str(video_key).strip()
    if key.startswith("http://") or key.startswith("https://"):
        return key
    try:
        from app.storage.r2 import generate_signed_url

        return generate_signed_url(key)
    except Exception:
        return None


def _build_options(
    *,
    part: int,
    q: SpeakingBuilderQuestionIn,
) -> dict[str, Any]:
    speak = int(q.speak_time_sec) if q.speak_time_sec is not None else 15
    min_skip = int(q.min_skip_sec) if q.min_skip_sec is not None else 5
    if min_skip > speak:
        min_skip = speak
    prep = int(q.prep_sec) if q.prep_sec is not None else (60 if part == 2 else 0)
    record = (
        int(q.record_sec)
        if q.record_sec is not None
        else _default_record_sec(part)
    )
    video_key = (q.video_url or "").strip() or None
    opts: dict[str, Any] = {
        "kind": _default_kind(part),
        "part_label": _default_part_label(part),
        "speak_time_sec": max(1, speak),
        "min_skip_sec": max(0, min_skip),
        "prep_sec": max(0, prep),
        "prep_seconds": max(0, prep),
        "record_sec": max(1, record),
        "max_record_sec": max(1, record),
        "max_recording_seconds": max(1, record),
        "duration_hint_sec": max(1, record),
        "video_url": video_key,
    }
    return opts


def _enable_speaking_module(sb: Any, mock_id: str) -> None:
    """Mark Speaking enabled so the student hub lists it (L → R → W → S)."""
    try:
        sb.table("mock_test_modules").upsert(
            {
                "mock_test_id": mock_id,
                "module": "speaking",
                "sequence_order": 4,
                "duration_minutes": 14,
                "is_enabled": True,
            },
            on_conflict="mock_test_id,module",
        ).execute()
    except Exception:
        # Fallback for older schemas / partial rows.
        try:
            sb.table("mock_test_modules").update({"is_enabled": True}).eq(
                "mock_test_id", mock_id
            ).eq("module", "speaking").execute()
        except Exception:
            pass


def save_speaking_part(
    *,
    mock_id: UUID,
    part: int,
    body: SpeakingBuilderSaveRequest,
    admin_id: UUID,
) -> SpeakingBuilderSaveResponse:
    if part < 1 or part > 3:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Part must be 1–3.")
    if not body.questions:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "At least one speaking question is required.",
        )

    for i, q in enumerate(body.questions, start=1):
        if not q.prompt.strip():
            label = "Cue card" if part == 2 else "Prompt"
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{label} is required for question {i}.",
            )
        if part == 2 and not (q.video_url or "").strip():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Part 2 requires a short examiner video (upload 10–15s clip).",
            )

    sb = get_supabase()
    mid = str(mock_id)
    _assert_mock_exists(sb, mid)

    existing = (
        sb.table("questions")
        .select("id")
        .eq("mock_test_id", mid)
        .eq("module", "speaking")
        .eq("part", part)
        .execute()
    ).data or []
    qids = [str(r["id"]) for r in existing]
    if qids:
        sb.table("answers").delete().in_("question_id", qids).execute()
        sb.table("question_versions").delete().in_("question_id", qids).execute()
    sb.table("questions").delete().eq("mock_test_id", mid).eq(
        "module", "speaking"
    ).eq("part", part).execute()

    inserts: list[dict[str, Any]] = []
    for i, q in enumerate(body.questions, start=1):
        inserts.append(
            {
                "mock_test_id": mid,
                "module": "speaking",
                "part": part,
                "question_number": i,
                "question_type": _default_question_type(part),
                "prompt": q.prompt.strip(),
                "options": _build_options(part=part, q=q),
                "skill_tag": _default_question_type(part),
            }
        )

    sb.table("questions").insert(inserts).execute()
    _enable_speaking_module(sb, mid)

    log_admin_action(
        admin_id=admin_id,
        action="speaking.builder_save",
        resource_type="mock_test",
        resource_id=mock_id,
        metadata={"part": part, "question_count": len(inserts)},
    )

    return SpeakingBuilderSaveResponse(
        ok=True,
        questions_written=len(inserts),
        part=part,
    )


def load_speaking_part(*, mock_id: UUID, part: int) -> SpeakingPartResponse:
    if part < 1 or part > 3:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Part must be 1–3.")

    sb = get_supabase()
    rows = (
        sb.table("questions")
        .select("id, question_number, question_type, prompt, options")
        .eq("mock_test_id", str(mock_id))
        .eq("module", "speaking")
        .eq("part", part)
        .order("question_number")
        .execute()
    ).data or []

    questions: list[SpeakingBuilderQuestionOut] = []
    for row in rows:
        opts = row.get("options") if isinstance(row.get("options"), dict) else {}
        video_key = opts.get("video_url") if isinstance(opts, dict) else None
        video_key_str = str(video_key).strip() if video_key else None
        if video_key_str == "":
            video_key_str = None
        video_name = video_key_str.split("/")[-1] if video_key_str else None
        speak = int(opts.get("speak_time_sec") or 15)
        min_skip = int(opts.get("min_skip_sec") or 5)
        prep = int(opts.get("prep_sec") or opts.get("prep_seconds") or (60 if part == 2 else 0))
        record = int(
            opts.get("record_sec")
            or opts.get("max_record_sec")
            or opts.get("max_recording_seconds")
            or _default_record_sec(part)
        )
        questions.append(
            SpeakingBuilderQuestionOut(
                id=UUID(str(row["id"])),
                question_number=int(row["question_number"]),
                prompt=str(row.get("prompt") or ""),
                speak_time_sec=speak,
                min_skip_sec=min_skip,
                prep_sec=prep,
                record_sec=record,
                video_url=video_key_str,
                video_preview_url=_signed_preview(video_key_str),
                video_name=video_name,
            )
        )

    return SpeakingPartResponse(
        mock_test_id=mock_id,
        part=part,
        questions=questions,
    )
