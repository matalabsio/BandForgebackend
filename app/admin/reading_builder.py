"""Admin reading builder — save/load passage + questions, individual CRUD."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.admin.answer_format import (
    expand_choose_two_rows,
    join_answers,
    parse_choose_two_letters,
    split_answers,
)
from app.admin.audit import log_admin_action
from app.admin.question_types import to_slug
from app.admin.schemas import (
    CreateQuestionRequest,
    CreateQuestionResponse,
    DeleteQuestionResponse,
    ReadingBuilderQuestionIn,
    ReadingBuilderQuestionOut,
    ReadingBuilderSaveRequest,
    ReadingBuilderSaveResponse,
    ReadingPassageResponse,
    UpdateQuestionRequest,
    UpdateQuestionResponse,
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


def save_reading_passage(
    *,
    mock_id: UUID,
    part: int,
    body: ReadingBuilderSaveRequest,
    admin_id: UUID,
) -> ReadingBuilderSaveResponse:
    sb = get_supabase()
    _assert_mock_exists(sb, str(mock_id))

    existing = (
        sb.table("questions")
        .select("id")
        .eq("mock_test_id", str(mock_id))
        .eq("module", "reading")
        .eq("part", part)
        .execute()
    ).data or []
    qids = [str(r["id"]) for r in existing]
    if qids:
        sb.table("answers").delete().in_("question_id", qids).execute()
        sb.table("question_versions").delete().in_("question_id", qids).execute()
    sb.table("questions").delete().eq("mock_test_id", str(mock_id)).eq(
        "module", "reading"
    ).eq("part", part).execute()

    inserts: list[dict[str, Any]] = []
    qnum = 1
    for q in body.questions:
        slug = to_slug(q.question_type)
        letters = parse_choose_two_letters(q.correct_answer)
        base: dict[str, Any] = {
            "mock_test_id": str(mock_id),
            "module": "reading",
            "part": part,
            "question_type": slug,
            "prompt": q.prompt,
            "passage_text": body.passage_text if qnum == 1 else None,
            "options": q.options,
            "skill_tag": q.skill_tag or slug,
        }
        if slug == "mcq" and len(letters) >= 2:
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
            if qnum > 1:
                row["passage_text"] = None
            inserts.append(row)
            qnum += 1

    sb.table("questions").insert(inserts).execute()

    _invalidate_reading_caches(mock_id=str(mock_id), part=part)

    log_admin_action(
        admin_id=admin_id,
        action="reading.builder_save",
        resource_type="mock_test",
        resource_id=mock_id,
        metadata={"part": part, "question_count": len(inserts)},
    )

    return ReadingBuilderSaveResponse(
        ok=True, questions_written=len(inserts), part=part
    )


def load_reading_passage(
    *, mock_id: UUID, part: int
) -> ReadingPassageResponse:
    sb = get_supabase()
    rows = (
        sb.table("questions")
        .select("id, question_number, question_type, prompt, passage_text, options, correct_answer, skill_tag")
        .eq("mock_test_id", str(mock_id))
        .eq("module", "reading")
        .eq("part", part)
        .order("question_number")
        .execute()
    ).data or []

    passage_text: str | None = None
    questions: list[ReadingBuilderQuestionOut] = []
    for row in rows:
        if passage_text is None and row.get("passage_text"):
            passage_text = str(row["passage_text"])
        primary, alts = split_answers(row.get("correct_answer"))
        questions.append(
            ReadingBuilderQuestionOut(
                id=UUID(str(row["id"])),
                question_number=int(row["question_number"]),
                question_type=str(row["question_type"]),
                prompt=str(row.get("prompt") or ""),
                passage_text=row.get("passage_text"),
                options=row.get("options"),
                correct_answer=primary,
                alt_answers=alts,
                skill_tag=row.get("skill_tag"),
            )
        )

    return ReadingPassageResponse(
        mock_test_id=mock_id,
        part=part,
        passage_text=passage_text,
        questions=questions,
    )


def create_question(
    *, body: CreateQuestionRequest, admin_id: UUID
) -> CreateQuestionResponse:
    sb = get_supabase()
    _assert_mock_exists(sb, str(body.mock_test_id))

    slug = to_slug(body.question_type)
    insert = {
        "mock_test_id": str(body.mock_test_id),
        "module": body.module,
        "part": body.part,
        "question_number": body.question_number,
        "question_type": slug,
        "prompt": body.prompt,
        "passage_text": body.passage_text,
        "options": body.options,
        "correct_answer": body.correct_answer,
        "skill_tag": body.skill_tag or slug,
    }
    result = sb.table("questions").insert(insert).execute()
    row = result.data[0]

    log_admin_action(
        admin_id=admin_id,
        action="question.create",
        resource_type="question",
        resource_id=UUID(str(row["id"])),
        metadata={"module": body.module, "part": body.part},
    )

    return CreateQuestionResponse(
        id=UUID(str(row["id"])),
        question_number=int(row["question_number"]),
        question_type=str(row["question_type"]),
        prompt=str(row["prompt"]),
    )


def delete_question(
    *, question_id: UUID, admin_id: UUID
) -> DeleteQuestionResponse:
    sb = get_supabase()
    result = (
        sb.table("questions")
        .select("id, mock_test_id, module, part, question_number")
        .eq("id", str(question_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found.")
    row = result.data[0]

    sb.table("answers").delete().eq("question_id", str(question_id)).execute()
    sb.table("question_versions").delete().eq("question_id", str(question_id)).execute()
    sb.table("questions").delete().eq("id", str(question_id)).execute()

    _renumber_questions(
        sb,
        mock_test_id=str(row["mock_test_id"]),
        module=str(row["module"]),
        part=int(row["part"]),
    )

    _invalidate_reading_caches(mock_id=str(row["mock_test_id"]), part=int(row["part"]))

    log_admin_action(
        admin_id=admin_id,
        action="question.delete",
        resource_type="question",
        resource_id=question_id,
        metadata={"module": row["module"], "part": row["part"]},
    )

    return DeleteQuestionResponse(ok=True, deleted_id=question_id)


def update_question(
    *, question_id: UUID, body: UpdateQuestionRequest, admin_id: UUID
) -> UpdateQuestionResponse:
    sb = get_supabase()
    result = (
        sb.table("questions")
        .select(
            "id, mock_test_id, module, part, question_number, "
            "question_type, prompt, correct_answer"
        )
        .eq("id", str(question_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found.")
    row = result.data[0]

    update: dict[str, Any] = {}
    if body.question_type is not None:
        update["question_type"] = to_slug(body.question_type)
    if body.prompt is not None:
        update["prompt"] = body.prompt
    if body.options is not None:
        update["options"] = body.options
    if body.correct_answer is not None:
        alt = body.alt_answers or []
        update["correct_answer"] = join_answers(body.correct_answer, alt)
    elif body.alt_answers is not None:
        existing_ca = row.get("correct_answer") or ""
        primary, _ = split_answers(existing_ca)
        update["correct_answer"] = join_answers(primary, body.alt_answers)
    if body.skill_tag is not None:
        update["skill_tag"] = body.skill_tag

    if update:
        sb.table("questions").update(update).eq("id", str(question_id)).execute()
        _invalidate_reading_caches(
            mock_id=str(row["mock_test_id"]), part=int(row["part"])
        )

    log_admin_action(
        admin_id=admin_id,
        action="question.update",
        resource_type="question",
        resource_id=question_id,
        metadata={"fields": list(update.keys())},
    )

    final_type = update.get("question_type", row["question_type"])
    final_prompt = update.get("prompt", row["prompt"])

    return UpdateQuestionResponse(
        id=question_id,
        question_number=int(row["question_number"]),
        question_type=str(final_type),
        prompt=str(final_prompt),
    )


def _renumber_questions(
    sb: Any, *, mock_test_id: str, module: str, part: int
) -> None:
    remaining = (
        sb.table("questions")
        .select("id, question_number")
        .eq("mock_test_id", mock_test_id)
        .eq("module", module)
        .eq("part", part)
        .order("question_number")
        .execute()
    ).data or []
    for i, row in enumerate(remaining, start=1):
        if int(row["question_number"]) != i:
            sb.table("questions").update({"question_number": i}).eq(
                "id", str(row["id"])
            ).execute()


def _invalidate_reading_caches(*, mock_id: str, part: int) -> None:
    try:
        from app.cache.hybrid_cache import delete_many

        delete_many([f"reading_questions:{mock_id}:{p}" for p in range(0, 5)])
    except Exception:
        pass
