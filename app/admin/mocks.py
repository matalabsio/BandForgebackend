"""Admin mock test catalog management."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.admin.audit import log_admin_action
from app.admin.schemas import (
    AdminMockDetail,
    AdminMockListItem,
    CreateMockRequest,
    DeleteMockResponse,
    MockModuleSummary,
    MockPartCount,
    ModuleSectionStatus,
    PatchMockRequest,
    PatchMockStatusRequest,
    SectionStatus,
)
from app.cache.hybrid_cache import delete_many
from app.db.supabase_client import execute_with_retry, get_supabase
from app.mock_catalog.catalog import live_parts_tuple, next_catalog_number


def _invalidate_picker_catalog() -> None:
    delete_many(["mock_catalog:v2:pub", "mock_catalog:v2:all"])


def _exec(query, *, retries: int = 3):
    return execute_with_retry(query.execute, retries=retries, base_delay_s=0.2)


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _fetch_modules_by_mock(sb: Any, mock_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not mock_ids:
        return {}
    rows = (
        _exec(
            sb.table("mock_test_modules")
            .select(
                "mock_test_id, module, sequence_order, duration_minutes, is_enabled"
            )
            .in_("mock_test_id", mock_ids)
            .order("sequence_order")
        ).data
        or []
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(str(row["mock_test_id"]), []).append(row)
    return out


def _fetch_section_rows(sb: Any, mock_id: str) -> list[dict[str, Any]]:
    return (
        _exec(
            sb.table("questions")
            .select("module, part, audio_url, options, prompt")
            .eq("mock_test_id", mock_id)
        ).data
        or []
    )


def _build_section_status(
    *,
    listening_parts: int,
    reading_passages: int,
    rows: list[dict[str, Any]],
) -> list[ModuleSectionStatus]:
    listening_counts: dict[int, int] = {}
    listening_audio: dict[int, bool] = {}
    reading_counts: dict[int, int] = {}
    speaking_counts: dict[int, int] = {}
    speaking_video: dict[int, bool] = {}

    for row in rows:
        mod = str(row.get("module") or "")
        part = int(row.get("part") or 1)
        if mod == "listening":
            listening_counts[part] = listening_counts.get(part, 0) + 1
            if row.get("audio_url"):
                listening_audio[part] = True
        elif mod == "reading":
            reading_counts[part] = reading_counts.get(part, 0) + 1
        elif mod == "speaking":
            speaking_counts[part] = speaking_counts.get(part, 0) + 1
            opts = row.get("options") if isinstance(row.get("options"), dict) else {}
            video = opts.get("video_url") if isinstance(opts, dict) else None
            if video and str(video).strip():
                speaking_video[part] = True

    return [
        ModuleSectionStatus(
            module="listening",
            sections=[
                SectionStatus(
                    part=p,
                    question_count=listening_counts.get(p, 0),
                    has_audio=listening_audio.get(p, False),
                )
                for p in range(1, listening_parts + 1)
            ],
        ),
        ModuleSectionStatus(
            module="reading",
            sections=[
                SectionStatus(
                    part=p,
                    question_count=reading_counts.get(p, 0),
                    has_audio=False,
                )
                for p in range(1, reading_passages + 1)
            ],
        ),
        ModuleSectionStatus(
            module="speaking",
            sections=[
                SectionStatus(
                    part=p,
                    question_count=speaking_counts.get(p, 0),
                    has_audio=speaking_video.get(p, False),
                )
                for p in range(1, 4)
            ],
        ),
    ]


def _publish_blockers(
    *,
    section_status: list[ModuleSectionStatus],
    enabled_modules: set[str],
) -> list[str]:
    blockers: list[str] = []

    for mod_status in section_status:
        if mod_status.module not in enabled_modules:
            continue
        if mod_status.module == "listening":
            for sec in mod_status.sections:
                if sec.question_count <= 0:
                    blockers.append(f"Listening section {sec.part}: no questions")
                elif not sec.has_audio:
                    blockers.append(
                        f"Listening section {sec.part}: missing audio (R2 key)"
                    )
        elif mod_status.module == "reading":
            for sec in mod_status.sections:
                if sec.question_count <= 0:
                    blockers.append(f"Reading passage {sec.part}: no questions")
        elif mod_status.module == "speaking":
            by_part = {sec.part: sec for sec in mod_status.sections}
            # Student flow starts with Part 1 (same as Test 1). Extra parts are optional.
            sec = by_part.get(1)
            if not sec or sec.question_count <= 0:
                blockers.append("Speaking Part 1: no questions")
            for p in (2, 3):
                sec = by_part.get(p)
                if not sec or sec.question_count <= 0:
                    continue
                if p == 2 and not sec.has_audio:
                    blockers.append(
                        "Speaking Part 2: missing short examiner video (R2)"
                    )

    if blockers:
        return blockers

    has_content = False
    for mod_status in section_status:
        if mod_status.module not in enabled_modules:
            continue
        if any(sec.question_count > 0 for sec in mod_status.sections):
            has_content = True
            break
    if not has_content:
        blockers.append(
            "At least one module must have ingested content before publishing."
        )
    return blockers


def _fetch_attempt_counts_by_mock(
    sb: Any, mock_ids: list[str]
) -> dict[str, int]:
    """Per-mock attempt counts via exact count queries (no full row download)."""
    if not mock_ids:
        return {}

    def count_one(mid: str) -> int:
        try:
            client = get_supabase()
            result = _exec(
                client.table("mock_attempts")
                .select("id", count="exact")
                .eq("mock_test_id", mid)
                .limit(1)
            )
            return int(result.count or 0)
        except Exception:
            return 0

    from app.admin.parallel import run_parallel

    return run_parallel({mid: (lambda m=mid: count_one(m)) for mid in mock_ids})


def _fetch_question_counts_by_mock(
    sb: Any, mock_ids: list[str]
) -> dict[str, dict[str, dict[int, int]]]:
    """mock_id -> module -> part -> count.

    Selects only the columns needed for aggregation.
    """
    if not mock_ids:
        return {}
    rows = (
        _exec(
            sb.table("questions")
            .select("mock_test_id, module, part")
            .in_("mock_test_id", mock_ids)
        ).data
        or []
    )
    out: dict[str, dict[str, dict[int, int]]] = {}
    for row in rows:
        mock_id = str(row["mock_test_id"])
        mod = str(row.get("module", ""))
        part = int(row.get("part") or 1)
        out.setdefault(mock_id, {}).setdefault(mod, {})
        out[mock_id][mod][part] = out[mock_id][mod].get(part, 0) + 1
    return out


def _module_summaries(
    *,
    mock_id: str,
    module_rows: list[dict[str, Any]],
    counts: dict[str, dict[int, int]],
) -> list[MockModuleSummary]:
    result: list[MockModuleSummary] = []
    for row in module_rows:
        mod = str(row["module"])
        part_counts = counts.get(mod, {})
        configured = live_parts_tuple(mock_test_id=mock_id, module=mod) or ()
        parts = sorted(part_counts.keys()) or list(configured)
        part_count_rows = [
            MockPartCount(part=int(p), question_count=int(part_counts.get(p, 0)))
            for p in parts
        ]
        result.append(
            MockModuleSummary(
                module=mod,
                sequence_order=int(row["sequence_order"]),
                duration_minutes=int(row["duration_minutes"]),
                is_enabled=bool(row["is_enabled"]),
                question_count=sum(part_counts.values()),
                parts=parts,
                part_counts=part_count_rows,
            )
        )
    return result


def _build_mock_list_item(
    row: dict[str, Any],
    *,
    module_rows: list[dict[str, Any]],
    counts: dict[str, dict[int, int]],
    attempt_count: int = 0,
) -> AdminMockListItem:
    mock_id = str(row["id"])
    total = sum(sum(parts.values()) for parts in counts.values())
    status_val = row.get("status") or (
        "published" if row.get("is_published") else "draft"
    )

    return AdminMockListItem(
        id=UUID(mock_id),
        title=str(row["title"]),
        description=row.get("description"),
        status=status_val,
        is_published=bool(row.get("is_published")),
        is_free=bool(row.get("is_free")),
        catalog_number=(
            int(row["catalog_number"])
            if row.get("catalog_number") is not None
            else None
        ),
        created_at=_parse_dt(row["created_at"]),
        total_questions=total,
        attempt_count=attempt_count,
        modules=_module_summaries(
            mock_id=mock_id,
            module_rows=module_rows,
            counts=counts,
        ),
    )


_MOCK_SELECT = (
    "id, title, description, status, is_published, is_free, created_at, catalog_number, "
    "listening_parts, reading_passages, writing_tasks"
)


def list_mocks() -> list[AdminMockListItem]:
    from app.admin.parallel import run_parallel
    from app.perf.timing import timed_call, timed_supabase

    sb = get_supabase()
    rows = timed_supabase(
        "mocks.list.mock_tests",
        lambda: _exec(sb.table("mock_tests").select(_MOCK_SELECT).order("created_at")),
    ).data or []
    rows.sort(
        key=lambda r: (
            r.get("catalog_number") is None,
            r.get("catalog_number") if r.get("catalog_number") is not None else 999,
            str(r.get("created_at") or ""),
        )
    )
    mock_ids = [str(row["id"]) for row in rows]
    if not mock_ids:
        return []

    fetched = timed_call(
        "mocks.list.aggregates_parallel",
        lambda: run_parallel(
            {
                "modules": lambda: _fetch_modules_by_mock(sb, mock_ids),
                "counts": lambda: _fetch_question_counts_by_mock(sb, mock_ids),
                "attempts": lambda: _fetch_attempt_counts_by_mock(sb, mock_ids),
            }
        ),
    )
    modules_by_mock = fetched["modules"]
    counts_by_mock = fetched["counts"]
    attempt_counts = fetched["attempts"]

    return [
        _build_mock_list_item(
            row,
            module_rows=modules_by_mock.get(str(row["id"]), []),
            counts=counts_by_mock.get(str(row["id"]), {}),
            attempt_count=attempt_counts.get(str(row["id"]), 0),
        )
        for row in rows
    ]


def get_mock_detail(mock_id: UUID) -> AdminMockDetail:
    sb = get_supabase()
    mock_key = str(mock_id)
    result = _exec(
        sb.table("mock_tests")
        .select(_MOCK_SELECT)
        .eq("id", mock_key)
        .limit(1)
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock test not found.")

    row = result.data[0]
    modules_by_mock = _fetch_modules_by_mock(sb, [mock_key])
    counts_by_mock = _fetch_question_counts_by_mock(sb, [mock_key])
    module_rows = modules_by_mock.get(mock_key, [])
    listening_parts = int(row.get("listening_parts") or 4)
    reading_passages = int(row.get("reading_passages") or 3)
    section_rows = _fetch_section_rows(sb, mock_key)
    section_status = _build_section_status(
        listening_parts=listening_parts,
        reading_passages=reading_passages,
        rows=section_rows,
    )
    enabled_modules = {
        str(m["module"]) for m in module_rows if m.get("is_enabled")
    }
    blockers = _publish_blockers(
        section_status=section_status,
        enabled_modules=enabled_modules,
    )
    base = _build_mock_list_item(
        row,
        module_rows=module_rows,
        counts=counts_by_mock.get(mock_key, {}),
    )
    return AdminMockDetail(
        **base.model_dump(),
        configured_listening_parts=listening_parts,
        configured_reading_passages=reading_passages,
        configured_writing_tasks=int(row.get("writing_tasks") or 2),
        section_status=section_status,
        publish_blockers=blockers,
    )


def _default_description(
    *,
    catalog_number: int,
    listening_parts: int,
    reading_passages: int,
    writing_tasks: int,
) -> str:
    return (
        f"Listening ({listening_parts} parts, 30 min) → "
        f"Reading ({reading_passages} passages, 30 min) → "
        f"Writing ({writing_tasks} tasks, 60 min) → "
        f"Speaking (Part 1, human-reviewed)."
    )


def _seed_mock_modules(sb: Any, mock_id: str) -> None:
    modules = [
        ("listening", 1, 30, True),
        ("reading", 2, 30, True),
        ("writing", 3, 60, True),
        ("speaking", 4, 14, True),
    ]
    _exec(
        sb.table("mock_test_modules").upsert(
            [
                {
                    "mock_test_id": mock_id,
                    "module": mod,
                    "sequence_order": seq,
                    "duration_minutes": mins,
                    "is_enabled": enabled,
                }
                for mod, seq, mins, enabled in modules
            ],
            on_conflict="mock_test_id,module",
        )
    )


def create_mock(*, body: CreateMockRequest, admin_id: UUID) -> AdminMockDetail:
    sb = get_supabase()
    catalog_number = body.catalog_number or next_catalog_number()
    description = body.description or _default_description(
        catalog_number=catalog_number,
        listening_parts=body.listening_parts,
        reading_passages=body.reading_passages,
        writing_tasks=body.writing_tasks,
    )

    inserted = _exec(
        sb.table("mock_tests")
        .insert(
            {
                "title": body.title,
                "description": description,
                "status": "draft",
                "is_published": False,
                "catalog_number": catalog_number,
                "listening_parts": body.listening_parts,
                "reading_passages": body.reading_passages,
                "writing_tasks": body.writing_tasks,
            }
        )
    )
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not create mock.")

    mock_id = str(inserted.data[0]["id"])
    _seed_mock_modules(sb, mock_id)

    log_admin_action(
        admin_id=admin_id,
        action="mock.create",
        resource_type="mock_test",
        resource_id=UUID(mock_id),
        metadata={"title": body.title, "catalog_number": catalog_number},
    )

    _invalidate_picker_catalog()
    return get_mock_detail(UUID(mock_id))


def patch_mock(
    *,
    mock_id: UUID,
    body: PatchMockRequest,
    admin_id: UUID,
) -> AdminMockDetail:
    sb = get_supabase()
    updates: dict[str, Any] = {}
    if body.title is not None:
        updates["title"] = body.title
    if body.description is not None:
        updates["description"] = body.description
    if body.catalog_number is not None:
        updates["catalog_number"] = body.catalog_number
    if body.listening_parts is not None:
        updates["listening_parts"] = body.listening_parts
    if body.reading_passages is not None:
        updates["reading_passages"] = body.reading_passages
    if body.writing_tasks is not None:
        updates["writing_tasks"] = body.writing_tasks
    if body.is_free is not None:
        updates["is_free"] = body.is_free

    if not updates:
        return get_mock_detail(mock_id)

    _exec(sb.table("mock_tests").update(updates).eq("id", str(mock_id)))

    log_admin_action(
        admin_id=admin_id,
        action="mock.update",
        resource_type="mock_test",
        resource_id=mock_id,
        metadata=updates,
    )

    _invalidate_picker_catalog()
    return get_mock_detail(mock_id)


def _verify_mock_content(mock_id: str) -> None:
    detail = get_mock_detail(UUID(mock_id))
    if detail.publish_blockers:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="; ".join(detail.publish_blockers),
        )


def patch_mock_status(
    *,
    mock_id: UUID,
    body: PatchMockStatusRequest,
    admin_id: UUID,
) -> AdminMockDetail:
    if body.status == "published":
        _verify_mock_content(str(mock_id))

    is_published = body.status == "published"
    sb = get_supabase()
    _exec(
        sb.table("mock_tests")
        .update({"status": body.status, "is_published": is_published})
        .eq("id", str(mock_id))
    )

    log_admin_action(
        admin_id=admin_id,
        action=f"mock.{body.status}",
        resource_type="mock_test",
        resource_id=mock_id,
        metadata={"status": body.status},
    )

    _invalidate_picker_catalog()
    return get_mock_detail(mock_id)


def delete_mock(*, mock_id: UUID, admin_id: UUID) -> DeleteMockResponse:
    """Permanently remove a draft or archived mock and its content.

    Published (live) mocks must be archived first.
    """
    sb = get_supabase()
    rows = (
        _exec(
            sb.table("mock_tests")
            .select("id, status, title, is_published")
            .eq("id", str(mock_id))
            .limit(1)
        )
    ).data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock test not found.")
    row = rows[0]
    status_val = str(
        row.get("status") or ("published" if row.get("is_published") else "draft")
    )
    if status_val == "published" or row.get("is_published"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Unpublish/archive this mock before deleting it.",
        )

    qrows = (
        _exec(
            sb.table("questions").select("id").eq("mock_test_id", str(mock_id))
        )
    ).data or []
    qids = [str(r["id"]) for r in qrows]
    if qids:
        for i in range(0, len(qids), 200):
            chunk = qids[i : i + 200]
            _exec(sb.table("answers").delete().in_("question_id", chunk))
            try:
                _exec(
                    sb.table("question_versions").delete().in_("question_id", chunk)
                )
            except Exception:
                pass
        _exec(sb.table("questions").delete().eq("mock_test_id", str(mock_id)))

    try:
        _exec(sb.table("mock_test_modules").delete().eq("mock_test_id", str(mock_id)))
    except Exception:
        pass

    try:
        _exec(sb.table("mock_attempts").delete().eq("mock_test_id", str(mock_id)))
    except Exception:
        pass

    _exec(sb.table("mock_tests").delete().eq("id", str(mock_id)))

    try:
        from app.cache.hybrid_cache import delete_many
        from app.listening.service import invalidate_listening_audio_caches

        invalidate_listening_audio_caches(mock_test_id=mock_id)
        delete_many([f"reading_questions:{mock_id}:{p}" for p in range(0, 5)])
    except Exception:
        pass

    log_admin_action(
        admin_id=admin_id,
        action="mock.delete",
        resource_type="mock_test",
        resource_id=mock_id,
        metadata={"title": row.get("title"), "status": status_val},
    )

    _invalidate_picker_catalog()
    return DeleteMockResponse(ok=True, deleted_id=mock_id)
