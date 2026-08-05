"""Admin listening builder — save/load part audio key + questions."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.admin.answer_format import (
    expand_choose_two_rows,
    join_answers,
    looks_like_choose_two_pair,
    split_answers,
)
from app.admin.audit import log_admin_action
from app.admin.listening_question_types import (
    MCQ_CHOOSE_TWO_UI,
    listening_to_display,
    listening_to_slug,
)
from app.admin.schemas import (
    ListeningBuilderQuestionOut,
    ListeningBuilderSaveRequest,
    ListeningBuilderSaveResponse,
    ListeningPartResponse,
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


def _is_choose_two(q_type_ui: str, correct: str, options: list | None) -> bool:
    if q_type_ui == MCQ_CHOOSE_TWO_UI:
        return True
    if listening_to_slug(q_type_ui) != "mcq":
        return False
    # Legacy heuristic: comma-separated multi correct among options
    parts = [p.strip() for p in (correct or "").split(",") if p.strip()]
    return len(parts) >= 2


def save_listening_part(
    *,
    mock_id: UUID,
    part: int,
    body: ListeningBuilderSaveRequest,
    admin_id: UUID,
) -> ListeningBuilderSaveResponse:
    if part < 1 or part > 4:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Part must be 1–4.")
    audio_key = body.audio_key.strip()
    if not audio_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "audio_key is required.")

    sb = get_supabase()
    _assert_mock_exists(sb, str(mock_id))

    existing = (
        sb.table("questions")
        .select("id")
        .eq("mock_test_id", str(mock_id))
        .eq("module", "listening")
        .eq("part", part)
        .execute()
    ).data or []
    qids = [str(r["id"]) for r in existing]
    if qids:
        sb.table("answers").delete().in_("question_id", qids).execute()
        sb.table("question_versions").delete().in_("question_id", qids).execute()
    sb.table("questions").delete().eq("mock_test_id", str(mock_id)).eq(
        "module", "listening"
    ).eq("part", part).execute()

    inserts: list[dict[str, Any]] = []
    qnum = 1
    for q in body.questions:
        slug = listening_to_slug(q.question_type)
        choose_two = bool(q.choose_two) or q.question_type == MCQ_CHOOSE_TWO_UI
        passage: str | None = None
        if qnum == 1 and body.instructions and body.instructions.strip():
            passage = body.instructions.strip()
        elif q.instructions and q.instructions.strip():
            passage = q.instructions.strip()

        base: dict[str, Any] = {
            "mock_test_id": str(mock_id),
            "module": "listening",
            "part": part,
            "question_type": slug,
            "prompt": q.prompt,
            "passage_text": passage,
            "options": q.options,
            "skill_tag": q.skill_tag or slug,
            "audio_url": audio_key,
        }
        if choose_two and slug == "mcq":
            rows = expand_choose_two_rows(
                base=base,
                correct_answer=q.correct_answer,
                alt_answers=q.alt_answers,
            )
        else:
            rows = [
                {
                    **base,
                    "correct_answer": join_answers(q.correct_answer, q.alt_answers),
                }
            ]
        for row in rows:
            row["question_number"] = qnum
            # Only first row of a choose-two pair keeps shared instructions
            if qnum > 1 and choose_two:
                row["passage_text"] = passage if q.instructions else None
            inserts.append(row)
            qnum += 1

    sb.table("questions").insert(inserts).execute()

    try:
        from app.listening.service import invalidate_listening_audio_caches

        invalidate_listening_audio_caches(mock_test_id=mock_id)
    except Exception:
        pass

    log_admin_action(
        admin_id=admin_id,
        action="listening.builder_save",
        resource_type="mock_test",
        resource_id=mock_id,
        metadata={
            "part": part,
            "question_count": len(inserts),
            "audio_key": audio_key,
        },
    )

    return ListeningBuilderSaveResponse(
        ok=True,
        questions_written=len(inserts),
        part=part,
        audio_key=audio_key,
    )


def load_listening_part(*, mock_id: UUID, part: int) -> ListeningPartResponse:
    if part < 1 or part > 4:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Part must be 1–4.")

    sb = get_supabase()
    rows = (
        sb.table("questions")
        .select(
            "id, question_number, question_type, prompt, passage_text, "
            "options, correct_answer, skill_tag, audio_url"
        )
        .eq("mock_test_id", str(mock_id))
        .eq("module", "listening")
        .eq("part", part)
        .order("question_number")
        .execute()
    ).data or []

    audio_key: str | None = None
    instructions: str | None = None
    questions: list[ListeningBuilderQuestionOut] = []

    i = 0
    while i < len(rows):
        row = rows[i]
        if audio_key is None and row.get("audio_url"):
            audio_key = str(row["audio_url"])
        if instructions is None and row.get("passage_text"):
            instructions = str(row["passage_text"])

        primary, alts = split_answers(row.get("correct_answer"))
        slug = str(row["question_type"])
        # Normalize legacy type aliases on read
        if slug.lower() in ("multiple_choice", "multiple-choice"):
            slug = "mcq"

        choose_two = _is_choose_two(slug, primary, row.get("options"))
        if slug == "mcq" and "," in primary:
            choose_two = True

        # Merge consecutive exam-style choose-two rows for admin edit UI
        if (
            i + 1 < len(rows)
            and looks_like_choose_two_pair(row, rows[i + 1])
        ):
            letters = [
                str(row.get("correct_answer") or "").strip().upper(),
                str(rows[i + 1].get("correct_answer") or "").strip().upper(),
            ]
            choose_two = True
            primary = ",".join(letters)
            alts = []
            i += 1  # skip partner row

        display = listening_to_display(slug, choose_two=choose_two)
        questions.append(
            ListeningBuilderQuestionOut(
                id=UUID(str(row["id"])),
                question_number=int(row["question_number"]),
                question_type=display,
                prompt=str(row.get("prompt") or ""),
                instructions=row.get("passage_text"),
                options=row.get("options"),
                correct_answer=primary,
                alt_answers=alts,
                skill_tag=row.get("skill_tag"),
                choose_two=choose_two,
            )
        )
        i += 1

    return ListeningPartResponse(
        mock_test_id=mock_id,
        part=part,
        audio_key=audio_key,
        instructions=instructions,
        questions=questions,
    )
