"""Admin question editing with versioning."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.admin.audit import log_admin_action
from app.admin.schemas import (
    AdminQuestionDetail,
    PatchQuestionRequest,
    QuestionTreeItem,
    QuestionTreeModule,
    QuestionTreePart,
    QuestionTreeResponse,
    QuestionVersionItem,
)
from app.db.supabase_client import get_supabase


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def get_question_tree(mock_id: UUID) -> QuestionTreeResponse:
    sb = get_supabase()
    rows = (
        sb.table("questions")
        .select("id, module, part, question_number, question_type, prompt")
        .eq("mock_test_id", str(mock_id))
        .order("module")
        .order("part")
        .order("question_number")
        .execute()
    ).data or []

    modules_map: dict[str, dict[int, list[QuestionTreeItem]]] = {}
    for row in rows:
        mod = str(row["module"])
        part = int(row.get("part") or 1)
        modules_map.setdefault(mod, {}).setdefault(part, []).append(
            QuestionTreeItem(
                id=UUID(str(row["id"])),
                question_number=int(row["question_number"]),
                question_type=str(row["question_type"]),
                prompt=str(row.get("prompt") or ""),
                part=part,
            )
        )

    modules: list[QuestionTreeModule] = []
    for mod in sorted(modules_map.keys()):
        parts: list[QuestionTreePart] = []
        for part_num in sorted(modules_map[mod].keys()):
            qs = modules_map[mod][part_num]
            parts.append(
                QuestionTreePart(
                    part=part_num,
                    question_count=len(qs),
                    questions=qs,
                )
            )
        modules.append(QuestionTreeModule(module=mod, parts=parts))

    return QuestionTreeResponse(mock_test_id=mock_id, modules=modules)


def _next_version(sb: Any, question_id: str) -> int:
    rows = (
        sb.table("question_versions")
        .select("version")
        .eq("question_id", question_id)
        .order("version", desc=True)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        return 1
    return int(rows[0]["version"]) + 1


def _snapshot_content(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "prompt": row.get("prompt"),
        "options": row.get("options"),
        "correct_answer": row.get("correct_answer"),
        "explanation": row.get("explanation"),
        "passage_text": row.get("passage_text"),
        "question_type": row.get("question_type"),
        "question_number": row.get("question_number"),
        "part": row.get("part"),
        "skill_tag": row.get("skill_tag"),
    }


def get_question_detail(question_id: UUID) -> AdminQuestionDetail:
    sb = get_supabase()
    result = (
        sb.table("questions")
        .select("*")
        .eq("id", str(question_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found.")
    row = result.data[0]

    versions_raw = (
        sb.table("question_versions")
        .select("id, version, content, created_at, created_by")
        .eq("question_id", str(question_id))
        .order("version", desc=True)
        .execute()
    ).data or []

    versions = [
        QuestionVersionItem(
            id=UUID(str(v["id"])),
            version=int(v["version"]),
            content=v.get("content") or {},
            created_at=_parse_dt(v["created_at"]),
            created_by=UUID(str(v["created_by"])) if v.get("created_by") else None,
        )
        for v in versions_raw
    ]

    return AdminQuestionDetail(
        id=UUID(str(row["id"])),
        mock_test_id=UUID(str(row["mock_test_id"])),
        module=str(row["module"]),
        part=int(row["part"]) if row.get("part") is not None else None,
        question_type=str(row["question_type"]),
        question_number=int(row["question_number"]),
        prompt=str(row.get("prompt") or ""),
        passage_text=row.get("passage_text"),
        options=row.get("options"),
        correct_answer=row.get("correct_answer"),
        explanation=row.get("explanation"),
        skill_tag=row.get("skill_tag"),
        versions=versions,
    )


def _normalize_options_payload(
    raw: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    if raw is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="options must be a list of {label, text} objects.",
        )
    if not isinstance(raw, list):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="options must be a list of {label, text} objects.",
        )
    if len(raw) < 2:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="MCQ options require at least 2 choices.",
        )

    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Each option must be an object with label and text.",
            )
        label = str(item.get("label") or item.get("letter") or "").strip()
        text = str(item.get("text") or "").strip()
        if not label:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Every option needs a non-empty label.",
            )
        if not text:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Option {label} needs non-empty text.",
            )
        key = label.upper()
        if key in seen:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate option label: {label}",
            )
        seen.add(key)
        normalized.append({"label": label, "text": text})
    return normalized


def _invalidate_student_question_caches(*, module: str, mock_test_id: str) -> None:
    if module == "listening":
        from app.listening.service import invalidate_listening_audio_caches

        invalidate_listening_audio_caches(mock_test_id=mock_test_id)
        return
    if module == "reading":
        from app.cache.hybrid_cache import delete_many

        delete_many([f"reading_questions:{mock_test_id}:{p}" for p in range(0, 5)])


def patch_question(
    *,
    question_id: UUID,
    body: PatchQuestionRequest,
    admin_id: UUID,
) -> AdminQuestionDetail:
    sb = get_supabase()
    result = (
        sb.table("questions")
        .select("*")
        .eq("id", str(question_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found.")
    row = result.data[0]

    updates: dict[str, Any] = {}
    if body.prompt is not None:
        updates["prompt"] = body.prompt
    if body.options is not None:
        updates["options"] = _normalize_options_payload(body.options)
    if body.correct_answer is not None:
        updates["correct_answer"] = body.correct_answer
    if body.explanation is not None:
        updates["explanation"] = body.explanation

    effective_options = updates.get("options", row.get("options"))
    effective_answer = updates.get("correct_answer", row.get("correct_answer"))
    if effective_options and effective_answer is not None:
        labels = {
            str(o.get("label") or "").strip()
            for o in effective_options
            if isinstance(o, dict)
        }
        answer = str(effective_answer).strip()
        if answer and answer not in labels:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="correct_answer must match one of the option labels.",
            )

    version = _next_version(sb, str(question_id))
    sb.table("question_versions").insert(
        {
            "question_id": str(question_id),
            "version": version,
            "content": _snapshot_content(row),
            "created_by": str(admin_id),
        }
    ).execute()

    if updates:
        sb.table("questions").update(updates).eq("id", str(question_id)).execute()
        _invalidate_student_question_caches(
            module=str(row.get("module") or ""),
            mock_test_id=str(row["mock_test_id"]),
        )

    log_admin_action(
        admin_id=admin_id,
        action="question.edit",
        resource_type="question",
        resource_id=question_id,
        metadata={"version": version, "fields": list(updates.keys())},
    )

    return get_question_detail(question_id)
