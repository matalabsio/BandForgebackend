"""Admin mock content ingest — validate and publish using existing normalizers."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.admin.audit import log_admin_action
from app.admin.schemas import (
    IngestPublishRequest,
    IngestPublishResponse,
    IngestValidateRequest,
    IngestValidateResponse,
)
from app.db.supabase_client import get_supabase


def _normalize_rows(
    *,
    mock_id: str,
    module: str,
    part: int,
    data: dict[str, Any],
    audio_key: str | None = None,
) -> list[dict[str, Any]]:
    if module == "reading":
        from scripts.normalize_reading_mock import flatten_questions

        rows = flatten_questions(data, part=part)
        for row in rows:
            row["mock_test_id"] = mock_id
        return rows

    if module == "listening":
        from scripts.normalize_listening_mock import normalize

        if not audio_key:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="audio_key is required for listening ingest.",
            )
        payload = normalize(
            data,
            mock_id=mock_id,
            audio_key=audio_key,
            allow_unsupported=False,
            part=part,
            renumber_per_part=True,
        )
        return list(payload.get("questions") or [])

    raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Unsupported module.")


def validate_ingest(body: IngestValidateRequest, mock_id: UUID) -> IngestValidateResponse:
    warnings: list[str] = []
    try:
        rows = _normalize_rows(
            mock_id=str(mock_id),
            module=body.module,
            part=body.part,
            data=body.data,
            audio_key=body.audio_key if body.module == "listening" else None,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Validation failed: {exc}",
        ) from exc

    preview = [
        {
            "question_number": r.get("question_number"),
            "question_type": r.get("question_type"),
            "prompt": (r.get("prompt") or "")[:120],
            "part": r.get("part"),
            **(
                {"audio_url": r.get("audio_url")}
                if body.module == "listening"
                else {}
            ),
        }
        for r in rows[:20]
    ]
    if len(rows) > 20:
        warnings.append(f"Showing 20 of {len(rows)} questions in preview.")

    if body.module == "listening":
        if not body.audio_key:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="audio_key is required for listening ingest.",
            )
        from app.storage.r2 import object_exists

        if not object_exists(body.audio_key):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Audio not found in R2 at key: {body.audio_key}. "
                    "Choose an MP3 and click Upload to R2 first."
                ),
            )

    return IngestValidateResponse(
        ok=True,
        question_count=len(rows),
        preview=preview,
        warnings=warnings,
    )


def _delete_scoped_questions(sb: Any, *, mock_id: str, module: str, part: int) -> None:
    existing = (
        sb.table("questions")
        .select("id")
        .eq("mock_test_id", mock_id)
        .eq("module", module)
        .eq("part", part)
        .execute()
    ).data or []
    qids = [str(r["id"]) for r in existing]
    if qids:
        sb.table("answers").delete().in_("question_id", qids).execute()
        sb.table("question_versions").delete().in_("question_id", qids).execute()
    sb.table("questions").delete().eq("mock_test_id", mock_id).eq(
        "module", module
    ).eq("part", part).execute()


def publish_ingest(
    *,
    mock_id: UUID,
    body: IngestPublishRequest,
    admin_id: UUID,
) -> IngestPublishResponse:
    sb = get_supabase()
    mock_row = (
        sb.table("mock_tests")
        .select("id")
        .eq("id", str(mock_id))
        .limit(1)
        .execute()
    ).data
    if not mock_row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock test not found.")

    try:
        rows = _normalize_rows(
            mock_id=str(mock_id),
            module=body.module,
            part=body.part,
            data=body.data,
            audio_key=body.audio_key,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Publish failed: {exc}",
        ) from exc

    if not rows:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No questions.")

    if body.module == "listening":
        if not body.audio_key:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="audio_key is required for listening publish.",
            )
        from app.storage.r2 import object_exists

        if not object_exists(body.audio_key):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Audio not found in R2 at key: {body.audio_key}",
            )

    _delete_scoped_questions(sb, mock_id=str(mock_id), module=body.module, part=body.part)

    inserts: list[dict[str, Any]] = []
    for row in rows:
        inserts.append(
            {
                "mock_test_id": str(mock_id),
                "module": body.module,
                "question_type": row.get("question_type"),
                "question_number": int(row.get("question_number") or 1),
                "part": int(row.get("part") or body.part),
                "prompt": row.get("prompt"),
                "passage_text": row.get("passage_text"),
                "options": row.get("options"),
                "correct_answer": row.get("correct_answer"),
                "skill_tag": row.get("skill_tag"),
                "audio_url": row.get("audio_url"),
            }
        )

    sb.table("questions").insert(inserts).execute()

    log_admin_action(
        admin_id=admin_id,
        action="mock.ingest_publish",
        resource_type="mock_test",
        resource_id=mock_id,
        metadata={
            "module": body.module,
            "part": body.part,
            "question_count": len(inserts),
        },
    )

    return IngestPublishResponse(
        ok=True,
        questions_written=len(inserts),
        module=body.module,
        part=body.part,
    )
