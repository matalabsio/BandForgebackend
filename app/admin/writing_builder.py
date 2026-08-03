"""Admin writing builder — save/load Task 1 / Task 2 prompts (+ Task 1 image key)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.admin.audit import log_admin_action
from app.admin.schemas import (
    WritingBuilderSaveRequest,
    WritingBuilderSaveResponse,
    WritingPartResponse,
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
    return "task1_academic" if part == 1 else "task2"


def _default_min_words(part: int) -> int:
    return 150 if part == 1 else 250


def _default_options(part: int) -> dict[str, Any]:
    return {
        "min_words": _default_min_words(part),
        "image_url": None,
        "title": f"WRITING TASK {part}",
    }


def _merge_options(
    *,
    part: int,
    existing: dict[str, Any] | None,
    body_options: dict[str, Any] | None,
    image_url: str | None,
) -> dict[str, Any]:
    merged: dict[str, Any] = dict(_default_options(part))
    if isinstance(existing, dict):
        merged.update(existing)
    if isinstance(body_options, dict):
        merged.update(body_options)
    if image_url is not None:
        key = image_url.strip()
        merged["image_url"] = key if key else None
    if "min_words" not in merged or not merged["min_words"]:
        merged["min_words"] = _default_min_words(part)
    return merged


def _invalidate_writing_caches(*, mock_id: str, part: int) -> None:
    try:
        from app.cache.hybrid_cache import delete_many

        delete_many([f"writing_task:{mock_id}:{part}"])
    except Exception:
        pass


def _signed_preview(image_key: str | None) -> str | None:
    if not image_key or not image_key.strip():
        return None
    key = image_key.strip()
    if key.startswith("http://") or key.startswith("https://"):
        return key
    try:
        from app.storage.r2 import generate_signed_url

        return generate_signed_url(key)
    except Exception:
        return None


def save_writing_part(
    *,
    mock_id: UUID,
    part: int,
    body: WritingBuilderSaveRequest,
    admin_id: UUID,
) -> WritingBuilderSaveResponse:
    if part < 1 or part > 2:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Part must be 1–2.")
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Prompt is required.")

    sb = get_supabase()
    _assert_mock_exists(sb, str(mock_id))

    existing_rows = (
        sb.table("questions")
        .select("id, options")
        .eq("mock_test_id", str(mock_id))
        .eq("module", "writing")
        .eq("part", part)
        .execute()
    ).data or []

    existing_options: dict[str, Any] | None = None
    if existing_rows:
        raw_opts = existing_rows[0].get("options")
        if isinstance(raw_opts, dict):
            existing_options = raw_opts

    qids = [str(r["id"]) for r in existing_rows]
    if qids:
        sb.table("answers").delete().in_("question_id", qids).execute()
        sb.table("question_versions").delete().in_("question_id", qids).execute()
    sb.table("questions").delete().eq("mock_test_id", str(mock_id)).eq(
        "module", "writing"
    ).eq("part", part).execute()

    question_type = (body.question_type or "").strip() or _default_question_type(part)
    options = _merge_options(
        part=part,
        existing=existing_options,
        body_options=body.options,
        image_url=body.image_url if part == 1 else None,
    )
    if part != 1:
        options["image_url"] = None

    insert = {
        "mock_test_id": str(mock_id),
        "module": "writing",
        "part": part,
        "question_number": 1,
        "question_type": question_type,
        "prompt": prompt,
        "options": options,
    }
    sb.table("questions").insert(insert).execute()

    _invalidate_writing_caches(mock_id=str(mock_id), part=part)

    image_key = options.get("image_url")
    image_key_str = str(image_key) if image_key else None

    log_admin_action(
        admin_id=admin_id,
        action="writing.builder_save",
        resource_type="mock_test",
        resource_id=mock_id,
        metadata={
            "part": part,
            "question_type": question_type,
            "image_url": image_key_str,
        },
    )

    return WritingBuilderSaveResponse(
        ok=True,
        part=part,
        question_type=question_type,
        image_url=image_key_str,
    )


def load_writing_part(*, mock_id: UUID, part: int) -> WritingPartResponse:
    if part < 1 or part > 2:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Part must be 1–2.")

    sb = get_supabase()
    rows = (
        sb.table("questions")
        .select("id, question_type, prompt, options")
        .eq("mock_test_id", str(mock_id))
        .eq("module", "writing")
        .eq("part", part)
        .order("question_number")
        .limit(1)
        .execute()
    ).data or []

    if not rows:
        return WritingPartResponse(
            mock_test_id=mock_id,
            part=part,
            question_type=_default_question_type(part),
            prompt="",
            options=_default_options(part),
            image_url=None,
            image_preview_url=None,
            image_name=None,
        )

    row = rows[0]
    opts = row.get("options") if isinstance(row.get("options"), dict) else {}
    image_key = opts.get("image_url") if isinstance(opts, dict) else None
    image_key_str = str(image_key).strip() if image_key else None
    if image_key_str == "":
        image_key_str = None

    image_name = None
    if image_key_str:
        image_name = image_key_str.split("/")[-1]

    return WritingPartResponse(
        mock_test_id=mock_id,
        part=part,
        question_id=UUID(str(row["id"])),
        question_type=str(row.get("question_type") or _default_question_type(part)),
        prompt=str(row.get("prompt") or ""),
        options=opts if isinstance(opts, dict) else _default_options(part),
        image_url=image_key_str,
        image_preview_url=_signed_preview(image_key_str),
        image_name=image_name,
    )
