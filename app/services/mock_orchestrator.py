"""Exam orchestration: mock_attempt lifecycle, sequential unlock, module grouping."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.config import get_settings
from app.cache.hybrid_cache import delete_many, get_json, invalidate_prefix, set_json
from app.cache.mock_cache import (
    invalidate_mock_history_caches,
    invalidate_mock_progress_caches,
)
from app.mock_catalog.constants import (
    M01_MOCK_TEST_ID,
    PUBLISHED_FULL_MOCK_IDS,
    enabled_modules_in_catalog_order,
)
from app.schemas.mock_orchestrator import (
    CheckpointSkillEntry,
    InProgressMockAttempt,
    MockAttemptProgress,
    MockAttemptSummary,
    MockCatalogItem,
    MockCheckpointResponse,
    ModuleProgress,
    SectionScore,
    StartMockResponse,
)
from app.schemas.test_engine import TestSummary
from app.services import mock_orchestrator_repository as repo


def _is_dev() -> bool:
    return get_settings().app_env.strip().lower() == "development"


def _first_enabled_module(modules: list[dict[str, Any]]) -> str:
    ordered = enabled_modules_in_catalog_order(modules)
    if not ordered:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="This mock has no enabled modules.",
        )
    return str(ordered[0]["module"])


def _first_part_for_module(mock_test_id: UUID, module: str) -> int:
    parts = repo.live_question_parts(mock_test_id=mock_test_id, module=module)
    return parts[0] if parts else 1


def _next_part_for_module(
    *,
    mock_test_id: UUID,
    module: str,
    module_attempts: list[dict[str, Any]],
) -> int:
    parts = repo.live_question_parts(mock_test_id=mock_test_id, module=module)
    if not parts:
        return 1
    done = {
        int(a["part"])
        for a in module_attempts
        if a.get("module") == module
        and a.get("status") == "completed"
        and a.get("part") is not None
    }
    for p in parts:
        if p not in done:
            return p
    return parts[0]


def _module_parts_complete(
    *,
    mock_test_id: UUID,
    module: str,
    module_attempts: list[dict[str, Any]],
) -> bool:
    required = repo.live_question_parts(mock_test_id=mock_test_id, module=module)
    completed_parts = {
        int(a["part"])
        for a in module_attempts
        if a.get("module") == module
        and a.get("status") == "completed"
        and a.get("part") is not None
    }
    return all(p in completed_parts for p in required)


def _score_raw_and_total(score_row: dict[str, Any]) -> tuple[int, int]:
    raw = score_row.get("correct_count")
    if raw is None:
        raw = score_row.get("raw_score")
    total = score_row.get("total_count")
    return int(raw or 0), int(total or 0)


def _parse_skill_breakdown(
    raw: Any,
) -> dict[str, CheckpointSkillEntry]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, CheckpointSkillEntry] = {}
    for skill, v in raw.items():
        if isinstance(v, dict):
            out[str(skill)] = CheckpointSkillEntry(
                correct=int(v.get("correct", 0)),
                total=int(v.get("total", 0)),
                pct=float(v.get("pct", 0.0)),
            )
    return out


def _module_rollup_band_from_scores(
    *,
    module: str,
    mock_test_id: UUID,
    module_attempts: list[dict[str, Any]],
    scores_by_attempt: dict[str, dict[str, Any]],
) -> float | None:
    if not _module_parts_complete(
        mock_test_id=mock_test_id,
        module=module,
        module_attempts=module_attempts,
    ):
        return None
    bands: list[float] = []
    for attempt in module_attempts:
        if attempt.get("module") != module or attempt.get("status") != "completed":
            continue
        row = scores_by_attempt.get(str(attempt["id"]))
        if row and row.get("band") is not None:
            bands.append(float(row["band"]))
    if not bands:
        return None
    return round(sum(bands) / len(bands), 1)


def _compute_module_statuses(
    *,
    mock_test_id: UUID,
    modules: list[dict[str, Any]],
    module_attempts: list[dict[str, Any]],
    scores_by_attempt: dict[str, dict[str, Any]] | None = None,
    include_bands: bool = True,
) -> list[ModuleProgress]:
    enabled = enabled_modules_in_catalog_order(modules)
    result: list[ModuleProgress] = []
    prior_complete = True

    for seq_idx, row in enumerate(enabled, start=1):
        mod = str(row["module"])
        mod_attempts = [a for a in module_attempts if a.get("module") == mod]
        completed = _module_parts_complete(
            mock_test_id=mock_test_id,
            module=mod,
            module_attempts=mod_attempts,
        )
        live_parts = repo.live_question_parts(mock_test_id=mock_test_id, module=mod)
        done_parts = {
            int(a["part"])
            for a in mod_attempts
            if a.get("status") == "completed" and a.get("part") is not None
        }
        in_prog = next(
            (
                a
                for a in mod_attempts
                if a.get("status") == "in_progress"
                and (
                    a.get("part") is None
                    or int(a["part"]) not in done_parts
                )
            ),
            None,
        )
        partial = bool(done_parts) and not completed and not all(
            p in done_parts for p in live_parts
        )

        if completed:
            st = "completed"
        elif in_prog or partial:
            st = "in_progress"
        elif prior_complete:
            st = "available"
        else:
            st = "locked"

        band: float | None = None
        test_attempt_id: UUID | None = None
        part: int | None = None
        if completed:
            last = max(
                (a for a in mod_attempts if a.get("status") == "completed"),
                key=lambda a: a.get("completed_at") or "",
                default=None,
            )
            if last:
                test_attempt_id = UUID(str(last["id"]))
                part = int(last["part"]) if last.get("part") is not None else None
                if include_bands:
                    score_row = (scores_by_attempt or {}).get(str(test_attempt_id))
                    if score_row and score_row.get("band") is not None:
                        band = float(score_row["band"])
                    elif scores_by_attempt is None:
                        band = repo.get_module_score_band(test_attempt_id)
        elif in_prog:
            test_attempt_id = UUID(str(in_prog["id"]))
            part = int(in_prog["part"]) if in_prog.get("part") is not None else None

        result.append(
            ModuleProgress(
                module=mod,  # type: ignore[arg-type]
                sequence_order=seq_idx,
                status=st,  # type: ignore[arg-type]
                duration_minutes=int(row["duration_minutes"]),
                is_enabled=True,
                band=band,
                test_attempt_id=test_attempt_id,
                part=part,
            )
        )
        prior_complete = prior_complete and completed

    return result


def list_catalog(*, include_unpublished: bool = False) -> list[MockCatalogItem]:
    from app.db.supabase_client import get_supabase

    sb = get_supabase()
    ids = list(PUBLISHED_FULL_MOCK_IDS)
    query = sb.table("mock_tests").select("id, title, description, is_published").in_(
        "id", ids
    )
    if not include_unpublished:
        query = query.eq("is_published", True)
    rows = list((query.execute()).data or [])

    items: list[MockCatalogItem] = []
    for row in rows:
        mock_id = UUID(str(row["id"]))
        modules = repo.list_mock_modules(mock_id)
        enabled_mods = [str(m["module"]) for m in modules if m.get("is_enabled")]
        l_parts = len(repo.live_question_parts(mock_test_id=mock_id, module="listening"))
        r_parts = len(repo.live_question_parts(mock_test_id=mock_id, module="reading"))
        items.append(
            MockCatalogItem(
                id=mock_id,
                title=str(row["title"]),
                description=row.get("description"),
                modules_enabled=enabled_mods,  # type: ignore[arg-type]
                listening_parts=l_parts,
                reading_passages=r_parts,
            )
        )
    return items


def get_progress(*, mock_attempt_id: UUID, user_id: UUID) -> MockAttemptProgress:
    cache_key = f"mock_progress:{mock_attempt_id}:{user_id}"
    cached = get_json(cache_key)
    if isinstance(cached, dict):
        try:
            return MockAttemptProgress.model_validate(cached)
        except Exception:
            pass
    row, mock_test_id, modules, module_attempts, scores = _load_mock_attempt_context(
        mock_attempt_id=mock_attempt_id, user_id=user_id
    )
    progress = _progress_from_context(
        row=row,
        mock_test_id=mock_test_id,
        modules=modules,
        module_attempts=module_attempts,
        scores_by_attempt=scores,
        include_bands=True,
    )
    set_json(cache_key, progress.model_dump(mode="json"), ttl_seconds=30)
    return progress


def _bundle_parts(
    bundle: dict[str, Any], *, user_id: UUID
) -> tuple[dict[str, Any], UUID, list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    row = bundle["mock_attempt"]
    if str(row.get("user_id")) != str(user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied.")
    mock_test_id = UUID(str(row["mock_test_id"]))
    modules = list(bundle.get("modules") or [])
    module_attempts = list(bundle.get("module_attempts") or [])
    scores_list = bundle.get("module_scores") or []
    scores = {
        str(s["attempt_id"]): s
        for s in scores_list
        if s.get("attempt_id") is not None
    }
    return row, mock_test_id, modules, module_attempts, scores


def _load_mock_attempt_context(
    *, mock_attempt_id: UUID, user_id: UUID
) -> tuple[dict[str, Any], UUID, list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    bundle = repo.fetch_mock_attempt_progress_bundle(
        mock_attempt_id=mock_attempt_id, user_id=user_id
    )
    if not bundle:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock attempt not found.")
    return _bundle_parts(bundle, user_id=user_id)


def _progress_from_bundle(
    bundle: dict[str, Any], *, user_id: UUID, include_bands: bool = True
) -> MockAttemptProgress:
    row, mock_test_id, modules, module_attempts, scores = _bundle_parts(
        bundle, user_id=user_id
    )
    return _progress_from_context(
        row=row,
        mock_test_id=mock_test_id,
        modules=modules,
        module_attempts=module_attempts,
        scores_by_attempt=scores if include_bands else {},
        include_bands=include_bands,
    )


def _merge_module_attempt_row(
    *,
    mock_attempt_id: UUID,
    module_attempts: list[dict[str, Any]],
    attempt_id: UUID,
    module: str,
    part: int,
) -> list[dict[str, Any]]:
    """Replace in-progress row for same module/part; append new attempt."""
    filtered = [
        a
        for a in module_attempts
        if not (
            str(a.get("module")) == module
            and int(a.get("part") or 1) == part
            and str(a.get("status")) == "in_progress"
        )
    ]
    filtered.append(
        {
            "id": str(attempt_id),
            "module": module,
            "part": part,
            "status": "in_progress",
            "mock_attempt_id": str(mock_attempt_id),
        }
    )
    return filtered


def _assert_mock_attempt_owner(*, mock_attempt_id: UUID, user_id: UUID) -> dict[str, Any]:
    from app.db.supabase_client import get_supabase

    client = get_supabase()
    ma = (
        client.table("mock_attempts")
        .select("id, user_id, mock_test_id, status, started_at, completed_at, current_module")
        .eq("id", str(mock_attempt_id))
        .limit(1)
        .execute()
    )
    rows = ma.data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock attempt not found.")
    row = rows[0]
    if str(row["user_id"]) != str(user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied.")
    return row


def _load_mock_attempt_context_legacy(
    *, mock_attempt_id: UUID, user_id: UUID
) -> tuple[dict[str, Any], UUID, list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    row = _assert_mock_attempt_owner(mock_attempt_id=mock_attempt_id, user_id=user_id)
    mock_test_id = UUID(str(row["mock_test_id"]))
    modules = repo.list_mock_modules(mock_test_id)
    module_attempts = repo.list_module_attempts(mock_attempt_id)
    completed_ids = [
        UUID(str(a["id"]))
        for a in module_attempts
        if a.get("status") == "completed"
    ]
    scores = repo.list_module_scores_by_attempt_ids(completed_ids)
    return row, mock_test_id, modules, module_attempts, scores


def _progress_from_context(
    *,
    row: dict[str, Any],
    mock_test_id: UUID,
    modules: list[dict[str, Any]],
    module_attempts: list[dict[str, Any]],
    scores_by_attempt: dict[str, dict[str, Any]],
    include_bands: bool,
) -> MockAttemptProgress:
    module_progress = _compute_module_statuses(
        mock_test_id=mock_test_id,
        modules=modules,
        module_attempts=module_attempts,
        scores_by_attempt=scores_by_attempt if include_bands else {},
        include_bands=include_bands,
    )

    next_module: str | None = None
    next_part: int | None = None
    for mp in module_progress:
        if mp.status == "available":
            next_module = mp.module
            next_part = _next_part_for_module(
                mock_test_id=mock_test_id,
                module=mp.module,
                module_attempts=module_attempts,
            )
            break
        if mp.status == "in_progress":
            next_module = mp.module
            next_part = _next_part_for_module(
                mock_test_id=mock_test_id,
                module=mp.module,
                module_attempts=module_attempts,
            )
            break

    bands = [mp.band for mp in module_progress if mp.band is not None]
    aggregate = round(sum(bands) / len(bands), 1) if bands else None

    started = row["started_at"]
    if isinstance(started, str):
        started_at = datetime.fromisoformat(started.replace("Z", "+00:00"))
    else:
        started_at = started or datetime.now(UTC)

    completed_raw = row.get("completed_at")
    completed_at = None
    if completed_raw:
        completed_at = (
            datetime.fromisoformat(completed_raw.replace("Z", "+00:00"))
            if isinstance(completed_raw, str)
            else completed_raw
        )

    return MockAttemptProgress(
        mock_attempt_id=UUID(str(row["id"])),
        mock_test_id=mock_test_id,
        status=str(row["status"]),
        started_at=started_at,
        completed_at=completed_at,
        current_module=row.get("current_module"),  # type: ignore[arg-type]
        modules=module_progress,
        next_module=next_module,  # type: ignore[arg-type]
        next_part=next_part,
        aggregate_band=aggregate,
    )


def get_summary(*, mock_attempt_id: UUID, user_id: UUID) -> MockAttemptSummary:
    row, mock_test_id, modules, module_attempts, scores = _load_mock_attempt_context(
        mock_attempt_id=mock_attempt_id, user_id=user_id
    )
    progress = _progress_from_context(
        row=row,
        mock_test_id=mock_test_id,
        modules=modules,
        module_attempts=module_attempts,
        scores_by_attempt=scores,
        include_bands=True,
    )

    sections: list[SectionScore] = []
    for attempt in module_attempts:
        if attempt.get("status") != "completed":
            continue
        score_row = scores.get(str(attempt["id"]))
        part_raw = attempt.get("part")
        raw_score: int | None = None
        total_questions: int | None = None
        band: float | None = None
        if score_row:
            raw, total = _score_raw_and_total(score_row)
            raw_score = raw
            total_questions = total
            if score_row.get("band") is not None:
                band = float(score_row["band"])
        sections.append(
            SectionScore(
                test_attempt_id=UUID(str(attempt["id"])),
                module=str(attempt["module"]),  # type: ignore[arg-type]
                part=int(part_raw) if part_raw is not None else None,
                raw_score=raw_score,
                total_questions=total_questions,
                band=band,
            )
        )
    sections.sort(key=lambda s: (s.module, s.part or 0))

    reading_band = _module_rollup_band_from_scores(
        module="reading",
        mock_test_id=mock_test_id,
        module_attempts=module_attempts,
        scores_by_attempt=scores,
    )
    listening_band = _module_rollup_band_from_scores(
        module="listening",
        mock_test_id=mock_test_id,
        module_attempts=module_attempts,
        scores_by_attempt=scores,
    )
    writing_band = _module_rollup_band_from_scores(
        module="writing",
        mock_test_id=mock_test_id,
        module_attempts=module_attempts,
        scores_by_attempt=scores,
    )

    return MockAttemptSummary(
        **progress.model_dump(),
        sections=sections,
        reading_band=reading_band,
        listening_band=listening_band,
        writing_band=writing_band,
    )


def get_checkpoint(
    *,
    mock_attempt_id: UUID,
    attempt_id: UUID,
    user_id: UUID,
) -> MockCheckpointResponse:
    row, mock_test_id, modules, module_attempts, scores = _load_mock_attempt_context(
        mock_attempt_id=mock_attempt_id, user_id=user_id
    )
    attempt = next(
        (a for a in module_attempts if str(a["id"]) == str(attempt_id)),
        None,
    )
    if not attempt or attempt.get("status") != "completed":
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Completed attempt not found for this mock.",
        )
    score_row = scores.get(str(attempt_id))
    if not score_row:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Score not available for this attempt.",
        )

    progress = _progress_from_context(
        row=row,
        mock_test_id=mock_test_id,
        modules=modules,
        module_attempts=module_attempts,
        scores_by_attempt=scores,
        include_bands=False,
    )
    raw_score, total_questions = _score_raw_and_total(score_row)

    return MockCheckpointResponse(
        attempt_id=attempt_id,
        band=float(score_row.get("band") or 0.0),
        raw_score=raw_score,
        total_questions=total_questions,
        skill_breakdown=_parse_skill_breakdown(score_row.get("skill_breakdown")),
        status=progress.status,
        next_module=progress.next_module,
        next_part=progress.next_part,
        reading_band=_module_rollup_band_from_scores(
            module="reading",
            mock_test_id=mock_test_id,
            module_attempts=module_attempts,
            scores_by_attempt=scores,
        ),
        listening_band=_module_rollup_band_from_scores(
            module="listening",
            mock_test_id=mock_test_id,
            module_attempts=module_attempts,
            scores_by_attempt=scores,
        ),
        modules=progress.modules,
    )


def list_attempt_history_lite(
    *, mock_test_id: UUID, user_id: UUID
) -> list["MockAttemptHistoryLiteItem"]:
    from app.schemas.mock_orchestrator import MockAttemptHistoryLiteItem

    cache_key = f"mock_history_lite:{user_id}:{mock_test_id}"
    cached = get_json(cache_key)
    if isinstance(cached, list):
        try:
            return [MockAttemptHistoryLiteItem.model_validate(item) for item in cached]
        except Exception:
            pass

    rows = repo.list_user_mock_attempts(
        user_id=user_id, mock_test_id=mock_test_id, limit=10
    )
    items: list[MockAttemptHistoryLiteItem] = []
    for row in rows:
        started = row["started_at"]
        if isinstance(started, str):
            started_at = datetime.fromisoformat(started.replace("Z", "+00:00"))
        else:
            started_at = started

        completed_raw = row.get("completed_at")
        completed_at = None
        if completed_raw:
            completed_at = (
                datetime.fromisoformat(completed_raw.replace("Z", "+00:00"))
                if isinstance(completed_raw, str)
                else completed_raw
            )

        items.append(
            MockAttemptHistoryLiteItem(
                mock_attempt_id=UUID(str(row["id"])),
                status=str(row["status"]),
                started_at=started_at,
                completed_at=completed_at,
            )
        )
    set_json(
        cache_key,
        [item.model_dump(mode="json") for item in items],
        ttl_seconds=60,
    )
    return items


def list_attempt_history(
    *, mock_test_id: UUID, user_id: UUID
) -> list["MockAttemptHistoryItem"]:
    from app.schemas.mock_orchestrator import MockAttemptHistoryItem

    cache_key = f"mock_history:{user_id}:{mock_test_id}"
    cached = get_json(cache_key)
    if isinstance(cached, list):
        try:
            return [MockAttemptHistoryItem.model_validate(item) for item in cached]
        except Exception:
            pass

    rows = repo.list_user_mock_attempts(
        user_id=user_id, mock_test_id=mock_test_id, limit=10
    )
    if not rows:
        set_json(cache_key, [], ttl_seconds=45)
        return []

    mock_ids = [UUID(str(row["id"])) for row in rows]
    attempts_by_mock = repo.list_module_attempts_by_mock_ids(mock_ids)
    completed_ids: list[UUID] = []
    for attempts in attempts_by_mock.values():
        completed_ids.extend(
            UUID(str(a["id"]))
            for a in attempts
            if a.get("status") == "completed"
        )
    scores = repo.list_module_scores_by_attempt_ids(completed_ids)

    items: list[MockAttemptHistoryItem] = []
    for row in rows:
        mock_attempt_id = UUID(str(row["id"]))
        module_attempts = attempts_by_mock.get(str(mock_attempt_id), [])
        reading_band = _module_rollup_band_from_scores(
            module="reading",
            mock_test_id=mock_test_id,
            module_attempts=module_attempts,
            scores_by_attempt=scores,
        )
        listening_band = _module_rollup_band_from_scores(
            module="listening",
            mock_test_id=mock_test_id,
            module_attempts=module_attempts,
            scores_by_attempt=scores,
        )
        writing_band = _module_rollup_band_from_scores(
            module="writing",
            mock_test_id=mock_test_id,
            module_attempts=module_attempts,
            scores_by_attempt=scores,
        )
        bands = [
            b
            for b in (listening_band, reading_band, writing_band)
            if b is not None
        ]
        aggregate = round(sum(bands) / len(bands), 1) if bands else None

        started = row["started_at"]
        if isinstance(started, str):
            started_at = datetime.fromisoformat(started.replace("Z", "+00:00"))
        else:
            started_at = started

        completed_raw = row.get("completed_at")
        completed_at = None
        if completed_raw:
            completed_at = (
                datetime.fromisoformat(completed_raw.replace("Z", "+00:00"))
                if isinstance(completed_raw, str)
                else completed_raw
            )

        items.append(
            MockAttemptHistoryItem(
                mock_attempt_id=mock_attempt_id,
                status=str(row.get("status") or "in_progress"),
                started_at=started_at,
                completed_at=completed_at,
                aggregate_band=aggregate,
                reading_band=reading_band,
                listening_band=listening_band,
            )
        )
    set_json(
        cache_key,
        [item.model_dump(mode="json") for item in items],
        ttl_seconds=45,
    )
    return items


def get_in_progress(
    *, mock_test_id: UUID, user_id: UUID
) -> InProgressMockAttempt | None:
    cache_key = f"mock_in_progress:{user_id}:{mock_test_id}"
    cached = get_json(cache_key)
    if isinstance(cached, dict):
        try:
            return InProgressMockAttempt.model_validate(cached)
        except Exception:
            pass

    row = repo.find_in_progress_mock_attempt(
        user_id=user_id, mock_test_id=mock_test_id
    )
    if not row:
        delete_many([cache_key])
        return None
    in_progress = InProgressMockAttempt(
        mock_attempt_id=UUID(str(row["id"])),
        mock_test_id=UUID(str(row["mock_test_id"])),
        status=str(row["status"]),
        current_module=row.get("current_module"),  # type: ignore[arg-type]
    )
    set_json(cache_key, in_progress.model_dump(mode="json"), ttl_seconds=10)
    return in_progress


def get_mock_session(
    *, mock_test_id: UUID, user_id: UUID
) -> MockAttemptProgress | None:
    """Return progress for the active or most recent mock attempt in one round trip."""
    cache_key = f"mock_session:{user_id}:{mock_test_id}"
    cached = get_json(cache_key)
    if isinstance(cached, dict):
        try:
            return MockAttemptProgress.model_validate(cached)
        except Exception:
            pass

    row = repo.find_in_progress_mock_attempt(
        user_id=user_id, mock_test_id=mock_test_id
    )
    if not row:
        rows = repo.list_user_mock_attempts(
            user_id=user_id, mock_test_id=mock_test_id, limit=1
        )
        row = rows[0] if rows else None

    if not row:
        delete_many([cache_key])
        return None

    progress = get_progress(
        mock_attempt_id=UUID(str(row["id"])), user_id=user_id
    )
    set_json(cache_key, progress.model_dump(mode="json"), ttl_seconds=30)
    return progress


def start_mock(
    *,
    mock_test_id: UUID,
    user_id: UUID,
    force_new: bool = False,
) -> StartMockResponse:
    """Create mock_attempt + first unlocked module test_attempt."""
    start_ctx = repo.fetch_mock_start_context(
        user_id=user_id,
        mock_test_id=mock_test_id,
        allow_unpublished=_is_dev(),
    )
    if not start_ctx or not start_ctx.get("mock_test"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock test not found.")

    test_row = start_ctx["mock_test"]
    modules = list(start_ctx.get("modules") or [])
    if not modules:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Mock has no module configuration. Run Supabase migrations "
                "20260526100000_mock_attempts_orchestration.sql and "
                "20260526100100_m01_consolidation.sql."
            ),
        )

    existing_ma = start_ctx.get("in_progress_attempt")
    if existing_ma and force_new:
        old_id = UUID(str(existing_ma["id"]))
        repo.abandon_in_progress_attempts_for_mock_attempt(mock_attempt_id=old_id)
        repo.update_mock_attempt(
            mock_attempt_id=old_id,
            fields={"status": "abandoned"},
        )
        existing_ma = None

    resumed = False
    if existing_ma:
        mock_attempt_id = UUID(str(existing_ma["id"]))
        resumed = True
    else:
        first_mod = _first_enabled_module(modules)
        ma_row = repo.insert_mock_attempt(
            user_id=user_id,
            mock_test_id=mock_test_id,
            current_module=first_mod,
        )
        mock_attempt_id = UUID(str(ma_row["id"]))

    bundle = repo.fetch_mock_attempt_progress_bundle(
        mock_attempt_id=mock_attempt_id, user_id=user_id
    )
    if not bundle:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock attempt not found.")

    progress = _progress_from_bundle(bundle, user_id=user_id)
    target = next(
        (m for m in progress.modules if m.status in ("available", "in_progress")),
        None,
    )
    if not target:
        if existing_ma and str(existing_ma.get("status")) == "in_progress":
            repo.update_mock_attempt(
                mock_attempt_id=mock_attempt_id,
                fields={
                    "status": "completed",
                    "completed_at": datetime.now(UTC).isoformat(),
                    "current_module": None,
                },
            )
            invalidate_mock_progress_caches(
                user_id=user_id,
                mock_test_id=mock_test_id,
                mock_attempt_id=mock_attempt_id,
            )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This test is complete. Start a new attempt to retake.",
        )

    start_module = target.module
    start_part = target.part or _first_part_for_module(mock_test_id, start_module)
    if not resumed and str(mock_test_id) == M01_MOCK_TEST_ID:
        start_module = "listening"
        start_part = 1

    module_attempt_id, part = _start_module_attempt(
        mock_attempt_id=mock_attempt_id,
        mock_test_id=mock_test_id,
        user_id=user_id,
        module=start_module,
        part=start_part,
        force_new=force_new or not resumed,
    )

    repo.update_mock_attempt(
        mock_attempt_id=mock_attempt_id,
        fields={"current_module": start_module},
    )

    row, _, _, module_attempts, scores = _bundle_parts(bundle, user_id=user_id)
    row = {**row, "current_module": start_module}
    module_attempts = _merge_module_attempt_row(
        mock_attempt_id=mock_attempt_id,
        module_attempts=module_attempts,
        attempt_id=module_attempt_id,
        module=start_module,
        part=part,
    )
    progress = _progress_from_context(
        row=row,
        mock_test_id=mock_test_id,
        modules=modules,
        module_attempts=module_attempts,
        scores_by_attempt=scores,
        include_bands=True,
    )

    invalidate_mock_progress_caches(
        user_id=user_id,
        mock_test_id=mock_test_id,
        mock_attempt_id=mock_attempt_id,
    )
    cache_key = f"mock_progress:{mock_attempt_id}:{user_id}"
    set_json(cache_key, progress.model_dump(mode="json"), ttl_seconds=30)
    session_key = f"mock_session:{user_id}:{mock_test_id}"
    set_json(session_key, progress.model_dump(mode="json"), ttl_seconds=30)

    return StartMockResponse(
        mock_attempt_id=mock_attempt_id,
        mock_test=TestSummary(
            id=UUID(str(test_row["id"])),
            title=str(test_row["title"]),
            description=test_row.get("description"),
        ),
        current_module=start_module,
        module_attempt_id=module_attempt_id,
        part=part,
        resumed=resumed,
        progress=progress,
    )


def _start_module_attempt(
    *,
    mock_attempt_id: UUID,
    mock_test_id: UUID,
    user_id: UUID,
    module: str,
    part: int,
    force_new: bool,
) -> tuple[UUID, int]:
    from app.listening import repository as listening_repo
    from app.reading import repository as reading_repo
    from app.writing import repository as writing_repo

    if module == "reading":
        existing = reading_repo.find_in_progress_reading_attempt(
            user_id=user_id,
            mock_test_id=mock_test_id,
            part=part,
            mock_attempt_id=mock_attempt_id,
        )
        if existing and force_new:
            reading_repo.abandon_reading_attempt(attempt_id=UUID(str(existing["id"])))
            existing = None
        if existing:
            return UUID(str(existing["id"])), part
        row = reading_repo.insert_reading_attempt(
            user_id=user_id,
            mock_test_id=mock_test_id,
            mock_attempt_id=mock_attempt_id,
            part=part,
        )
        return UUID(str(row["id"])), part

    if module == "listening":
        existing = listening_repo.find_in_progress_listening_attempt(
            user_id=user_id,
            mock_test_id=mock_test_id,
            part=part,
            mock_attempt_id=mock_attempt_id,
        )
        if existing and force_new:
            listening_repo.abandon_listening_attempt(attempt_id=UUID(str(existing["id"])))
            existing = None
        if existing:
            return UUID(str(existing["id"])), part
        row = listening_repo.insert_listening_attempt(
            user_id=user_id,
            mock_test_id=mock_test_id,
            mock_attempt_id=mock_attempt_id,
            part=part,
        )
        return UUID(str(row["id"])), part

    if module == "writing":
        existing = writing_repo.find_in_progress_writing_attempt(
            user_id=user_id,
            mock_test_id=mock_test_id,
            part=part,
            mock_attempt_id=mock_attempt_id,
        )
        if existing and force_new:
            writing_repo.abandon_writing_attempt(attempt_id=UUID(str(existing["id"])))
            existing = None
        if existing:
            return UUID(str(existing["id"])), part
        row = writing_repo.insert_writing_attempt(
            user_id=user_id,
            mock_test_id=mock_test_id,
            mock_attempt_id=mock_attempt_id,
            part=part,
        )
        return UUID(str(row["id"])), part

    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Module {module} is not available yet.",
    )


def assert_module_unlocked(
    *,
    mock_attempt_id: UUID | None,
    user_id: UUID,
    mock_test_id: UUID,
    module: str,
    part: int,
) -> None:
    """Raise 403 if sequential rules block this module/part."""
    if mock_attempt_id is None:
        return
    _assert_mock_attempt_owner(mock_attempt_id=mock_attempt_id, user_id=user_id)
    modules = repo.list_mock_modules(mock_test_id)
    module_attempts = repo.list_module_attempts(mock_attempt_id)
    module_progress = _compute_module_statuses(
        mock_test_id=mock_test_id,
        modules=modules,
        module_attempts=module_attempts,
        include_bands=False,
    )
    mp = next((m for m in module_progress if m.module == module), None)
    if not mp:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Unknown module.")
    live_parts = repo.live_question_parts(mock_test_id=mock_test_id, module=module)
    completed_attempts = [
        a
        for a in module_attempts
        if a.get("module") == module and a.get("status") == "completed"
    ]
    done_parts = {
        int(a["part"]) for a in completed_attempts if a.get("part") is not None
    }
    mod_attempts_for_module = [
        a for a in module_attempts if a.get("module") == module
    ]
    has_started_module = any(
        a.get("status") in ("completed", "in_progress")
        for a in mod_attempts_for_module
    )
    if mp.status == "locked" and not has_started_module:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Complete the previous module before starting this one.",
        )

    if part in done_parts:
        if module == "listening":
            label = "listening part"
        elif module == "writing":
            label = "writing task"
        else:
            label = "passage"
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=f"This {label} is already completed and cannot be reopened.",
        )
    if part not in live_parts:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="This section is not part of the current test flow.",
        )
    if not all(p in done_parts for p in live_parts if p < part):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Complete earlier sections in this module first.",
        )


def resume_mock(
    *, mock_attempt_id: UUID, user_id: UUID
) -> StartMockResponse:
    progress = get_progress(mock_attempt_id=mock_attempt_id, user_id=user_id)
    if progress.status != "in_progress":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This mock attempt is not in progress.",
        )
    next_mod = progress.next_module
    if not next_mod:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="No module available to resume.",
        )
    part = progress.next_part or _first_part_for_module(progress.mock_test_id, next_mod)
    module_attempt_id, part = _start_module_attempt(
        mock_attempt_id=mock_attempt_id,
        mock_test_id=progress.mock_test_id,
        user_id=user_id,
        module=next_mod,
        part=part,
        force_new=False,
    )
    test_row = repo.get_mock_test(progress.mock_test_id, allow_unpublished=_is_dev())
    repo.update_mock_attempt(
        mock_attempt_id=mock_attempt_id,
        fields={"current_module": next_mod},
    )
    invalidate_prefix(f"mock_session:{user_id}:")
    invalidate_prefix(f"mock_progress:{mock_attempt_id}:{user_id}")
    fresh_progress = get_progress(mock_attempt_id=mock_attempt_id, user_id=user_id)
    return StartMockResponse(
        mock_attempt_id=mock_attempt_id,
        mock_test=TestSummary(
            id=progress.mock_test_id,
            title=str(test_row["title"]),
            description=test_row.get("description"),
        ),
        current_module=next_mod,  # type: ignore[arg-type]
        module_attempt_id=module_attempt_id,
        part=part,
        resumed=True,
        progress=fresh_progress,
    )


def _finalize_mock_progress_after_submit(
    *,
    mock_attempt_id: UUID,
    mock_test_id: UUID,
    user_id: UUID,
    invalidate_history: bool = False,
) -> MockAttemptProgress:
    """One progress bundle fetch + cache warm after mock_attempt row updates."""
    invalidate_mock_progress_caches(
        user_id=user_id,
        mock_test_id=mock_test_id,
        mock_attempt_id=mock_attempt_id,
    )
    if invalidate_history:
        invalidate_mock_history_caches(user_id=user_id, mock_test_id=mock_test_id)

    bundle = repo.fetch_mock_attempt_progress_bundle(
        mock_attempt_id=mock_attempt_id, user_id=user_id
    )
    if not bundle:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock attempt not found.")
    progress = _progress_from_bundle(bundle, user_id=user_id)
    cache_key = f"mock_progress:{mock_attempt_id}:{user_id}"
    set_json(cache_key, progress.model_dump(mode="json"), ttl_seconds=30)
    set_json(
        f"mock_session:{user_id}:{mock_test_id}",
        progress.model_dump(mode="json"),
        ttl_seconds=30,
    )
    return progress


def on_module_attempt_completed(
    *,
    test_attempt_id: UUID,
    user_id: UUID,
    attempt: dict[str, Any] | None = None,
) -> MockAttemptProgress | None:
    """After module submit: advance mock_attempt or unlock next module."""
    if attempt is None:
        from app.db.supabase_client import get_supabase

        client = get_supabase()
        ta = (
            client.table("test_attempts")
            .select(
                "id, user_id, mock_test_id, module, part, mock_attempt_id, status, "
                "started_at, completed_at"
            )
            .eq("id", str(test_attempt_id))
            .limit(1)
            .execute()
        )
        rows = ta.data or []
        if not rows:
            return None
        attempt = rows[0]
    if str(attempt.get("user_id")) != str(user_id):
        return None

    mock_attempt_id_raw = attempt.get("mock_attempt_id")
    if not mock_attempt_id_raw:
        return None

    mock_attempt_id = UUID(str(mock_attempt_id_raw))
    mock_test_id = UUID(str(attempt["mock_test_id"]))
    module = str(attempt["module"])

    bundle = repo.fetch_mock_attempt_progress_bundle(
        mock_attempt_id=mock_attempt_id, user_id=user_id
    )
    if not bundle:
        return None
    modules = list(bundle.get("modules") or [])
    module_attempts = list(bundle.get("module_attempts") or [])

    if not _module_parts_complete(
        mock_test_id=mock_test_id,
        module=module,
        module_attempts=module_attempts,
    ):
        parts = repo.live_question_parts(mock_test_id=mock_test_id, module=module)
        done = {
            int(a["part"])
            for a in module_attempts
            if a.get("module") == module
            and a.get("status") == "completed"
            and a.get("part") is not None
        }
        remaining = [p for p in parts if p not in done]
        if remaining:
            repo.update_mock_attempt(
                mock_attempt_id=mock_attempt_id,
                fields={"current_module": module},
            )
            return _finalize_mock_progress_after_submit(
                mock_attempt_id=mock_attempt_id,
                mock_test_id=mock_test_id,
                user_id=user_id,
            )

    mod_order = [str(m["module"]) for m in enabled_modules_in_catalog_order(modules)]
    try:
        idx = mod_order.index(module)
    except ValueError:
        idx = -1

    if idx >= 0 and idx < len(mod_order) - 1:
        next_mod = mod_order[idx + 1]
        repo.update_mock_attempt(
            mock_attempt_id=mock_attempt_id,
            fields={"current_module": next_mod},
        )
        return _finalize_mock_progress_after_submit(
            mock_attempt_id=mock_attempt_id,
            mock_test_id=mock_test_id,
            user_id=user_id,
        )

    repo.update_mock_attempt(
        mock_attempt_id=mock_attempt_id,
        fields={
            "status": "completed",
            "completed_at": datetime.now(UTC).isoformat(),
            "current_module": None,
        },
    )
    return _finalize_mock_progress_after_submit(
        mock_attempt_id=mock_attempt_id,
        mock_test_id=mock_test_id,
        user_id=user_id,
        invalidate_history=True,
    )
