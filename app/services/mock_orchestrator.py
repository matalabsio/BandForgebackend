"""Exam orchestration: mock_attempt lifecycle, module unlock, module grouping."""

from __future__ import annotations

import os
from contextvars import ContextVar
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.config import get_settings
from app.cache.hybrid_cache import delete_many, get_json, invalidate_prefix, set_json
from app.cache.mock_cache import (
    invalidate_mock_progress_caches,
    read_progress_from_cache,
    read_unlock_snapshot,
    refresh_mock_in_progress_cache,
    schedule_mock_history_cache_invalidation,
    write_progress_cache,
    write_progress_cache_async,
    write_unlock_snapshot_cache,
)
from app.services.mock_progress_timing import MockProgressTiming, _elapsed_ms
from app.services.mock_start_timing import MockStartTiming, elapsed_ms as _start_elapsed_ms
from app.mock_catalog.constants import (
    M01_MOCK_TEST_ID,
    PUBLISHED_FULL_MOCK_IDS,
    enabled_modules_in_catalog_order,
)
from app.schemas.mock_orchestrator import (
    CheckpointSkillEntry,
    InProgressMockAttempt,
    MockAttemptProgress,
    MockUnlockSnapshot,
    ModuleProgressStatus,
    MockAttemptSummary,
    MockCatalogItem,
    MockCheckpointResponse,
    ModuleProgress,
    ModuleResultState,
    SectionScore,
    StartMockResponse,
)
from app.schemas.test_engine import TestSummary
from app.services import mock_orchestrator_repository as repo

# Request-scoped memo for live_question_parts (set during start_mock).
_live_parts_memo: ContextVar[dict[tuple[str, str], list[int]] | None] = ContextVar(
    "bf_live_parts_memo",
    default=None,
)


def _is_dev() -> bool:
    return get_settings().app_env.strip().lower() == "development"


def _mock_free_module_access() -> bool:
    """Testing mode: start any enabled module without sequential unlock.

    Override with MOCK_FREE_MODULE_ACCESS=0 to restore exam-order locks.
    Default: on (any non-falsey / unset env enables free access).
    """
    raw = os.environ.get("MOCK_FREE_MODULE_ACCESS", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _first_enabled_module(modules: list[dict[str, Any]]) -> str:
    ordered = enabled_modules_in_catalog_order(modules)
    if not ordered:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="This mock has no enabled modules.",
        )
    return str(ordered[0]["module"])


def _required_attempt_parts(mock_test_id: UUID, module: str) -> list[int]:
    memo = _live_parts_memo.get()
    key = (str(mock_test_id), module)
    if memo is not None and key in memo:
        return memo[key]
    question_parts = repo.live_question_parts(
        mock_test_id=mock_test_id,
        module=module,
    )
    # Speaking Parts 1–3 are captured and finalized as one durable attempt.
    result = [1] if module == "speaking" and question_parts else question_parts
    if memo is not None:
        memo[key] = result
    return result


def _first_part_for_module(mock_test_id: UUID, module: str) -> int:
    parts = _required_attempt_parts(mock_test_id, module)
    return parts[0] if parts else 1


def _next_part_for_module(
    *,
    mock_test_id: UUID,
    module: str,
    module_attempts: list[dict[str, Any]],
) -> int:
    parts = _required_attempt_parts(mock_test_id, module)
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
    required = _required_attempt_parts(mock_test_id, module)
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


_RESULT_MODULES = ("listening", "reading", "writing", "speaking")
_AI_COMPLETE_STATUSES = frozenset({"ai_complete", "ai_stub"})
_AI_FAILED_STATUSES = frozenset({"ai_failed", "failed"})
_AI_PROCESSING_STATUSES = frozenset(
    {"pending", "pending_multi_response", "queued", "processing", "retry_wait"}
)


def _latest_completed_attempts_by_part(
    module_attempts: list[dict[str, Any]], module: str
) -> dict[int, dict[str, Any]]:
    completed = [
        attempt
        for attempt in module_attempts
        if attempt.get("module") == module
        and attempt.get("status") == "completed"
        and attempt.get("part") is not None
    ]
    completed.sort(key=lambda attempt: str(attempt.get("completed_at") or ""), reverse=True)
    by_part: dict[int, dict[str, Any]] = {}
    for attempt in completed:
        by_part.setdefault(int(attempt["part"]), attempt)
    return by_part


def _valid_ai_band(module: str, review: dict[str, Any]) -> float | None:
    ai_scores = review.get("ai_scores")
    if not isinstance(ai_scores, dict):
        return None
    if str(ai_scores.get("status") or "") not in _AI_COMPLETE_STATUSES:
        return None
    if module == "speaking" and review.get("evaluation_status") != "completed":
        return None
    band = ai_scores.get("ai_band")
    try:
        parsed = float(band) if band is not None else None
    except (TypeError, ValueError):
        return None
    if parsed is None or not 0 <= parsed <= 9 or parsed * 2 != round(parsed * 2):
        return None
    return parsed


def _build_provisional_result_contract(
    *,
    mock_test_id: UUID,
    modules: list[dict[str, Any]],
    module_attempts: list[dict[str, Any]],
    scores_by_attempt: dict[str, dict[str, Any]],
    reviews_by_attempt: dict[str, dict[str, Any]],
    final_bands: dict[str, float | None],
    official_aggregate_band: float | None,
) -> tuple[dict[str, ModuleResultState], float | None, bool, bool]:
    enabled = {
        str(module["module"])
        for module in modules
        if module.get("is_enabled")
    }
    states: dict[str, ModuleResultState] = {}
    has_pending_reviews = False

    for module in _RESULT_MODULES:
        if module not in enabled:
            states[module] = ModuleResultState(source="unavailable")
            continue

        final_band = final_bands.get(module)
        if final_band is not None:
            states[module] = ModuleResultState(band=final_band, source="final")
            continue

        attempts = [
            attempt
            for attempt in module_attempts
            if attempt.get("module") == module
        ]
        if module in ("listening", "reading"):
            source = "processing" if attempts else "unavailable"
            states[module] = ModuleResultState(source=source)
            continue

        required_parts = _required_attempt_parts(mock_test_id, module)
        completed_by_part = _latest_completed_attempts_by_part(module_attempts, module)
        part_bands: list[float] = []
        used_ai = False
        saw_processing = False
        saw_failed = False
        saw_review = False

        for part in required_parts:
            attempt = completed_by_part.get(part)
            if attempt is None:
                saw_processing = saw_processing or bool(attempts)
                continue
            attempt_id = str(attempt["id"])
            score = scores_by_attempt.get(attempt_id)
            if score and score.get("band") is not None:
                part_bands.append(float(score["band"]))
                continue

            review = reviews_by_attempt.get(attempt_id) or {}
            if review:
                saw_review = True
                review_status = str(review.get("status") or "pending")
                if review_status in {"pending", "in_review"}:
                    has_pending_reviews = True
                ai_band = _valid_ai_band(module, review)
                if ai_band is not None:
                    part_bands.append(ai_band)
                    used_ai = True
                    continue
                ai_scores = review.get("ai_scores")
                ai_status = (
                    str(ai_scores.get("status") or "")
                    if isinstance(ai_scores, dict)
                    else ""
                )
                evaluation_status = str(review.get("evaluation_status") or "")
                if ai_status in _AI_FAILED_STATUSES or evaluation_status == "failed":
                    saw_failed = True
                elif (
                    ai_status in _AI_PROCESSING_STATUSES
                    or evaluation_status
                    in {"queued", "processing", "retry_wait", "not_queued"}
                ):
                    saw_processing = True

        if required_parts and len(part_bands) == len(required_parts):
            source = "ai_estimate" if used_ai else "final"
            states[module] = ModuleResultState(
                band=round(sum(part_bands) / len(part_bands), 1),
                source=source,
            )
        elif saw_processing:
            states[module] = ModuleResultState(source="processing")
        elif saw_failed:
            states[module] = ModuleResultState(source="failed")
        elif saw_review:
            states[module] = ModuleResultState(source="awaiting_examiner")
        else:
            source = "processing" if attempts else "unavailable"
            states[module] = ModuleResultState(source=source)

    enabled_states = [states[module] for module in _RESULT_MODULES if module in enabled]
    fully_final = bool(enabled_states) and all(
        state.source == "final" for state in enabled_states
    )
    provisional_bands = [
        state.band
        for state in enabled_states
        if state.source in {"final", "ai_estimate"} and state.band is not None
    ]
    provisional_aggregate = (
        (
            official_aggregate_band
            if official_aggregate_band is not None
            else (
                round(sum(provisional_bands) / len(provisional_bands), 1)
                if provisional_bands
                else None
            )
        )
        if fully_final
        else (
            round(sum(provisional_bands) / len(provisional_bands), 1)
            if provisional_bands
            else None
        )
    )
    aggregate_is_provisional = provisional_aggregate is not None and not fully_final
    return (
        states,  # type: ignore[return-value]
        provisional_aggregate,
        aggregate_is_provisional,
        has_pending_reviews,
    )


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
        live_parts = _required_attempt_parts(mock_test_id, mod)
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

        # Testing mode: every unfinished enabled module is startable.
        if st == "locked" and _mock_free_module_access():
            st = "available"

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
    """Published (or all, in dev) catalog slots for the mock picker.

    Uses part counts from ``mock_tests`` row fields instead of per-mock
    ``live_question_parts`` round trips. Result is cached briefly — catalog
    changes only when admins publish.
    """
    from app.mock_catalog.catalog import list_catalog_mock_rows
    from app.mock_catalog.constants import MODULE_LIVE_PARTS

    cache_key = f"mock_catalog:v2:{'all' if include_unpublished else 'pub'}"
    cached = get_json(cache_key)
    if isinstance(cached, list):
        try:
            return [MockCatalogItem.model_validate(item) for item in cached]
        except Exception:
            pass

    rows = list_catalog_mock_rows(include_unpublished=include_unpublished)
    mock_ids = [UUID(str(row["id"])) for row in rows]
    modules_by_id = repo.list_mock_modules_by_ids(mock_ids)

    items: list[MockCatalogItem] = []
    for row in rows:
        mock_id = UUID(str(row["id"]))
        mock_id_str = str(mock_id)
        modules = modules_by_id.get(mock_id_str) or []
        enabled_mods = [str(m["module"]) for m in modules if m.get("is_enabled")]

        legacy = MODULE_LIVE_PARTS.get(mock_id_str, {})
        listening_parts = (
            len(legacy["listening"])
            if "listening" in legacy
            else int(row.get("listening_parts") or 0)
        )
        reading_passages = (
            len(legacy["reading"])
            if "reading" in legacy
            else int(row.get("reading_passages") or 0)
        )

        items.append(
            MockCatalogItem(
                id=mock_id,
                title=str(row["title"]),
                description=row.get("description"),
                catalog_number=(
                    int(row["catalog_number"])
                    if row.get("catalog_number") is not None
                    else None
                ),
                modules_enabled=enabled_mods,  # type: ignore[arg-type]
                listening_parts=listening_parts,
                reading_passages=reading_passages,
                writing_tasks=int(row.get("writing_tasks") or 2),
            )
        )

    set_json(
        cache_key,
        [item.model_dump(mode="json") for item in items],
        ttl_seconds=60,
    )
    return items


def invalidate_catalog_cache() -> None:
    """Drop picker catalog cache after publish / unpublish / delete."""
    delete_many(["mock_catalog:v2:pub", "mock_catalog:v2:all"])


def get_progress(*, mock_attempt_id: UUID, user_id: UUID) -> MockAttemptProgress:
    cached_progress = read_progress_from_cache(
        mock_attempt_id=mock_attempt_id, user_id=user_id
    )
    if cached_progress is not None:
        return cached_progress
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
    unlock = build_unlock_snapshot(
        mock_test_id=mock_test_id,
        modules=modules,
        module_attempts=module_attempts,
        current_module=row.get("current_module"),
    )
    write_progress_cache(
        mock_attempt_id=mock_attempt_id,
        user_id=user_id,
        mock_test_id=mock_test_id,
        progress=progress,
        unlock=unlock,
    )
    return progress


def build_unlock_snapshot(
    *,
    mock_test_id: UUID,
    modules: list[dict[str, Any]],
    module_attempts: list[dict[str, Any]],
    current_module: str | None,
    module_progress: list[ModuleProgress] | None = None,
) -> MockUnlockSnapshot:
    if module_progress is None:
        module_progress = _compute_module_statuses(
            mock_test_id=mock_test_id,
            modules=modules,
            module_attempts=module_attempts,
            include_bands=False,
        )
    return _unlock_snapshot_from_progress(
        module_progress=module_progress,
        module_attempts=module_attempts,
        current_module=current_module,
    )


def _unlock_snapshot_from_progress(
    *,
    module_progress: list[ModuleProgress],
    module_attempts: list[dict[str, Any]],
    current_module: str | None,
) -> MockUnlockSnapshot:
    done_parts: dict[str, list[int]] = {}
    for attempt in module_attempts:
        if attempt.get("status") != "completed":
            continue
        part_raw = attempt.get("part")
        mod = str(attempt.get("module", ""))
        if not mod or part_raw is None:
            continue
        done_parts.setdefault(mod, []).append(int(part_raw))
    for mod, parts in done_parts.items():
        done_parts[mod] = sorted(set(parts))
    module_status = {mp.module: mp.status for mp in module_progress}
    return MockUnlockSnapshot(
        done_parts=done_parts,
        current_module=current_module,  # type: ignore[arg-type]
        module_status=module_status,  # type: ignore[arg-type]
    )


def _apply_started_module_to_progress(
    *,
    progress: MockAttemptProgress,
    start_module: str,
    module_attempt_id: UUID,
    part: int,
) -> MockAttemptProgress:
    """Patch progress after opening a module attempt without recomputing statuses."""
    updated_modules: list[ModuleProgress] = []
    for mp in progress.modules:
        if mp.module == start_module:
            updated_modules.append(
                mp.model_copy(
                    update={
                        "status": "in_progress",
                        "test_attempt_id": module_attempt_id,
                        "part": part,
                    }
                )
            )
        else:
            updated_modules.append(mp)
    return progress.model_copy(
        update={
            "current_module": start_module,  # type: ignore[arg-type]
            "modules": updated_modules,
            "next_module": start_module,  # type: ignore[arg-type]
            "next_part": part,
        }
    )


def _validate_unlock_from_snapshot(
    *,
    snapshot: MockUnlockSnapshot,
    mock_test_id: UUID,
    module: str,
    part: int,
) -> None:
    live_parts = repo.live_question_parts(mock_test_id=mock_test_id, module=module)
    done_parts = set(snapshot.done_parts.get(module, []))
    mp_status: ModuleProgressStatus | None = snapshot.module_status.get(module)  # type: ignore[arg-type]
    has_started_module = mp_status in ("completed", "in_progress") or bool(done_parts)
    if (
        mp_status == "locked"
        and not has_started_module
        and not _mock_free_module_access()
    ):
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock attempt not found.")
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
    if (
        module_progress
        and all(item.status == "completed" for item in module_progress)
        and str(row.get("status")) != "completed"
    ):
        completed_at = max(
            (
                str(item.get("completed_at"))
                for item in module_attempts
                if item.get("completed_at")
            ),
            default=datetime.now(UTC).isoformat(),
        )
        repair = {
            "status": "completed",
            "completed_at": completed_at,
            "current_module": None,
        }
        repo.update_mock_attempt(
            mock_attempt_id=UUID(str(row["id"])),
            fields=repair,
        )
        row = {**row, **repair}

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
    speaking_band = _module_rollup_band_from_scores(
        module="speaking",
        mock_test_id=mock_test_id,
        module_attempts=module_attempts,
        scores_by_attempt=scores,
    )
    review_attempt_ids = [
        UUID(str(attempt["id"]))
        for attempt in module_attempts
        if attempt.get("module") in {"writing", "speaking"}
        and attempt.get("status") == "completed"
    ]
    reviews = repo.list_module_reviews_by_attempt_ids(review_attempt_ids)
    (
        module_result_states,
        provisional_aggregate_band,
        aggregate_is_provisional,
        has_pending_reviews,
    ) = _build_provisional_result_contract(
        mock_test_id=mock_test_id,
        modules=modules,
        module_attempts=module_attempts,
        scores_by_attempt=scores,
        reviews_by_attempt=reviews,
        final_bands={
            "listening": listening_band,
            "reading": reading_band,
            "writing": writing_band,
            "speaking": speaking_band,
        },
        official_aggregate_band=progress.aggregate_band,
    )

    return MockAttemptSummary(
        **progress.model_dump(),
        sections=sections,
        reading_band=reading_band,
        listening_band=listening_band,
        writing_band=writing_band,
        speaking_band=speaking_band,
        provisional_aggregate_band=provisional_aggregate_band,
        aggregate_is_provisional=aggregate_is_provisional,
        has_pending_reviews=has_pending_reviews,
        module_result_states=module_result_states,  # type: ignore[arg-type]
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
        speaking_band = _module_rollup_band_from_scores(
            module="speaking",
            mock_test_id=mock_test_id,
            module_attempts=module_attempts,
            scores_by_attempt=scores,
        )
        bands = [
            b
            for b in (listening_band, reading_band, writing_band, speaking_band)
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
                writing_band=writing_band,
                speaking_band=speaking_band,
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


def get_mock_session_timed(
    *, mock_test_id: UUID, user_id: UUID
) -> tuple[MockAttemptProgress | None, dict[str, float | bool]]:
    """Return progress and timing metadata for GET /api/mock-attempts/session."""
    timing: dict[str, float | bool] = {
        "cache_hit": False,
        "find_mock_ms": 0.0,
        "progress_bundle_ms": 0.0,
    }
    cache_key = f"mock_session:v2:{user_id}:{mock_test_id}"
    cached = get_json(cache_key)
    if isinstance(cached, dict):
        try:
            timing["cache_hit"] = True
            return MockAttemptProgress.model_validate(cached), timing
        except Exception:
            pass

    t_find = perf_counter()
    row = repo.find_in_progress_mock_attempt(
        user_id=user_id, mock_test_id=mock_test_id
    )
    if not row:
        rows = repo.list_user_mock_attempts(
            user_id=user_id, mock_test_id=mock_test_id, limit=1
        )
        row = rows[0] if rows else None
    timing["find_mock_ms"] = round((perf_counter() - t_find) * 1000, 2)

    if not row:
        delete_many([cache_key])
        return None, timing

    t_progress = perf_counter()
    progress = get_progress(
        mock_attempt_id=UUID(str(row["id"])), user_id=user_id
    )
    timing["progress_bundle_ms"] = round((perf_counter() - t_progress) * 1000, 2)
    set_json(cache_key, progress.model_dump(mode="json"), ttl_seconds=30)
    return progress, timing


def get_mock_session(
    *, mock_test_id: UUID, user_id: UUID
) -> MockAttemptProgress | None:
    """Return progress for the active or most recent mock attempt in one round trip."""
    progress, _ = get_mock_session_timed(mock_test_id=mock_test_id, user_id=user_id)
    return progress


async def start_mock(
    *,
    mock_test_id: UUID,
    user_id: UUID,
    force_new: bool = False,
    timing: MockStartTiming | None = None,
    start_ctx: dict[str, Any] | None = None,
) -> StartMockResponse:
    """Create mock_attempt + first unlocked module test_attempt.

    Independent I/O uses ``asyncio.to_thread`` + ``asyncio.gather`` where safe.
    Pass ``start_ctx`` when the caller already loaded start/gate context.
    """
    import asyncio

    t_request = perf_counter()
    memo_token = _live_parts_memo.set({})
    if timing is not None:
        timing.force_new = force_new

    try:
        if start_ctx is None:
            t0 = perf_counter()
            start_ctx = await asyncio.to_thread(
                repo.fetch_mock_start_context,
                user_id=user_id,
                mock_test_id=mock_test_id,
                allow_unpublished=_is_dev(),
            )
            if timing is not None:
                timing.fetch_start_context_ms = _start_elapsed_ms(t0)

        if not start_ctx or not start_ctx.get("mock_test"):
            if timing is not None:
                timing.duration_ms = _start_elapsed_ms(t_request)
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock test not found.")

        test_row = start_ctx["mock_test"]
        t0 = perf_counter()
        catalog_number = test_row.get("catalog_number")
        if catalog_number is not None:
            from app.mock_catalog.constants import is_candidate_live_catalog_number

            if not is_candidate_live_catalog_number(int(catalog_number)):
                if timing is not None:
                    timing.catalog_validate_ms = _start_elapsed_ms(t0)
                    timing.duration_ms = _start_elapsed_ms(t_request)
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock test not found.")
        if timing is not None:
            timing.catalog_validate_ms = _start_elapsed_ms(t0)

        modules = list(start_ctx.get("modules") or [])
        if not modules:
            if timing is not None:
                timing.duration_ms = _start_elapsed_ms(t_request)
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
            t0 = perf_counter()
            old_id = UUID(str(existing_ma["id"]))
            await asyncio.to_thread(
                repo.abandon_mock_attempt_session,
                mock_attempt_id=old_id,
            )
            existing_ma = None
            if timing is not None:
                timing.abandon_existing_ms = _start_elapsed_ms(t0)

        resumed = False
        if existing_ma:
            mock_attempt_id = UUID(str(existing_ma["id"]))
            resumed = True
        else:
            first_mod = _first_enabled_module(modules)
            t0 = perf_counter()
            ma_row = await asyncio.to_thread(
                repo.insert_mock_attempt,
                user_id=user_id,
                mock_test_id=mock_test_id,
                current_module=first_mod,
            )
            if timing is not None:
                timing.insert_mock_attempt_ms = _start_elapsed_ms(t0)
            mock_attempt_id = UUID(str(ma_row["id"]))

        if timing is not None:
            timing.resumed = resumed

        t0 = perf_counter()
        bundle = await asyncio.to_thread(
            repo.fetch_mock_attempt_progress_bundle,
            mock_attempt_id=mock_attempt_id,
            user_id=user_id,
        )
        if timing is not None:
            timing.fetch_progress_bundle_ms = _start_elapsed_ms(t0)
        if not bundle:
            if timing is not None:
                timing.duration_ms = _start_elapsed_ms(t_request)
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock attempt not found.")

        # Prefer modules from start_ctx when present (same data, avoid relying on bundle only).
        if not bundle.get("modules") and modules:
            bundle = {**bundle, "modules": modules}

        t0 = perf_counter()
        progress = _progress_from_bundle(bundle, user_id=user_id)
        if timing is not None:
            timing.progress_from_bundle_ms = _start_elapsed_ms(t0)
        target = next(
            (m for m in progress.modules if m.status in ("available", "in_progress")),
            None,
        )
        if not target:
            if existing_ma and str(existing_ma.get("status")) == "in_progress":
                await asyncio.to_thread(
                    repo.update_mock_attempt,
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
            if timing is not None:
                timing.duration_ms = _start_elapsed_ms(t_request)
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="This test is complete. Start a new attempt to retake.",
            )

        start_module = target.module
        start_part = target.part or _first_part_for_module(mock_test_id, start_module)
        if not resumed and str(mock_test_id) == M01_MOCK_TEST_ID:
            start_module = "listening"
            start_part = 1

        if timing is not None:
            timing.start_module = start_module
            timing.start_part = start_part

        # After force_new session abandon the new mock_attempt_id has no children.
        module_force_new = (
            False if (force_new and not resumed) else (force_new or not resumed)
        )
        t0 = perf_counter()
        (module_attempt_id, part), _ = await asyncio.gather(
            asyncio.to_thread(
                _start_module_attempt,
                mock_attempt_id=mock_attempt_id,
                mock_test_id=mock_test_id,
                user_id=user_id,
                module=start_module,
                part=start_part,
                force_new=module_force_new,
                timing=timing,
            ),
            asyncio.to_thread(
                repo.update_mock_attempt,
                mock_attempt_id=mock_attempt_id,
                fields={"current_module": start_module},
            ),
        )
        if timing is not None:
            timing.start_module_ms = _start_elapsed_ms(t0)
            timing.update_current_module_ms = timing.start_module_ms

        t0 = perf_counter()
        row, _, bundle_modules, module_attempts, _scores = _bundle_parts(
            bundle, user_id=user_id
        )
        _ = bundle_modules
        row = {**row, "current_module": start_module}
        module_attempts = _merge_module_attempt_row(
            mock_attempt_id=mock_attempt_id,
            module_attempts=module_attempts,
            attempt_id=module_attempt_id,
            module=start_module,
            part=part,
        )
        # Reuse first progress compute — patch started module only (no second full recompute).
        progress = _apply_started_module_to_progress(
            progress=progress.model_copy(
                update={
                    "mock_attempt_id": mock_attempt_id,
                    "current_module": start_module,  # type: ignore[arg-type]
                }
            ),
            start_module=start_module,
            module_attempt_id=module_attempt_id,
            part=part,
        )
        if timing is not None:
            timing.progress_rebuild_ms = _start_elapsed_ms(t0)

        t0 = perf_counter()
        unlock = _unlock_snapshot_from_progress(
            module_progress=progress.modules,
            module_attempts=module_attempts,
            current_module=start_module,
        )
        if timing is not None:
            timing.unlock_snapshot_ms = _start_elapsed_ms(t0)

        t0 = perf_counter()
        await write_progress_cache_async(
            mock_attempt_id=mock_attempt_id,
            user_id=user_id,
            mock_test_id=mock_test_id,
            progress=progress,
            unlock=unlock,
        )
        if timing is not None:
            timing.write_cache_ms = _start_elapsed_ms(t0)
            timing.duration_ms = _start_elapsed_ms(t_request)

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
    finally:
        _live_parts_memo.reset(memo_token)


def _start_module_attempt(
    *,
    mock_attempt_id: UUID,
    mock_test_id: UUID,
    user_id: UUID,
    module: str,
    part: int,
    force_new: bool,
    timing: MockStartTiming | None = None,
) -> tuple[UUID, int]:
    from app.listening import repository as listening_repo
    from app.reading import repository as reading_repo
    from app.writing import repository as writing_repo

    if module == "reading":
        t0 = perf_counter()
        existing = reading_repo.find_in_progress_reading_attempt(
            user_id=user_id,
            mock_test_id=mock_test_id,
            part=part,
            mock_attempt_id=mock_attempt_id,
        )
        if timing is not None:
            timing.start_module_find_ms += _start_elapsed_ms(t0)
        if existing and force_new:
            t0 = perf_counter()
            reading_repo.abandon_reading_attempt(attempt_id=UUID(str(existing["id"])))
            if timing is not None:
                timing.start_module_abandon_ms += _start_elapsed_ms(t0)
            existing = None
        if existing:
            return UUID(str(existing["id"])), part
        t0 = perf_counter()
        row = reading_repo.insert_reading_attempt(
            user_id=user_id,
            mock_test_id=mock_test_id,
            mock_attempt_id=mock_attempt_id,
            part=part,
        )
        if timing is not None:
            timing.start_module_insert_ms += _start_elapsed_ms(t0)
        return UUID(str(row["id"])), part

    if module == "listening":
        t0 = perf_counter()
        existing = listening_repo.find_in_progress_listening_attempt(
            user_id=user_id,
            mock_test_id=mock_test_id,
            part=part,
            mock_attempt_id=mock_attempt_id,
        )
        if timing is not None:
            timing.start_module_find_ms += _start_elapsed_ms(t0)
        if existing and force_new:
            t0 = perf_counter()
            listening_repo.abandon_listening_attempt(attempt_id=UUID(str(existing["id"])))
            if timing is not None:
                timing.start_module_abandon_ms += _start_elapsed_ms(t0)
            existing = None
        if existing:
            return UUID(str(existing["id"])), part
        t0 = perf_counter()
        row = listening_repo.insert_listening_attempt(
            user_id=user_id,
            mock_test_id=mock_test_id,
            mock_attempt_id=mock_attempt_id,
            part=part,
        )
        if timing is not None:
            timing.start_module_insert_ms += _start_elapsed_ms(t0)
        return UUID(str(row["id"])), part

    if module == "writing":
        t0 = perf_counter()
        existing = writing_repo.find_in_progress_writing_attempt(
            user_id=user_id,
            mock_test_id=mock_test_id,
            part=part,
            mock_attempt_id=mock_attempt_id,
        )
        if timing is not None:
            timing.start_module_find_ms += _start_elapsed_ms(t0)
        if existing and force_new:
            t0 = perf_counter()
            writing_repo.abandon_writing_attempt(attempt_id=UUID(str(existing["id"])))
            if timing is not None:
                timing.start_module_abandon_ms += _start_elapsed_ms(t0)
            existing = None
        if existing:
            return UUID(str(existing["id"])), part
        t0 = perf_counter()
        row = writing_repo.insert_writing_attempt(
            user_id=user_id,
            mock_test_id=mock_test_id,
            mock_attempt_id=mock_attempt_id,
            part=part,
        )
        if timing is not None:
            timing.start_module_insert_ms += _start_elapsed_ms(t0)
        return UUID(str(row["id"])), part

    if module == "speaking":
        from app.speaking import repository as speaking_repo

        t0 = perf_counter()
        existing = speaking_repo.find_in_progress_speaking_attempt(
            user_id=user_id,
            mock_test_id=mock_test_id,
            part=part,
            mock_attempt_id=mock_attempt_id,
        )
        if timing is not None:
            timing.start_module_find_ms += _start_elapsed_ms(t0)
        if existing and force_new:
            t0 = perf_counter()
            speaking_repo.abandon_speaking_attempt(attempt_id=UUID(str(existing["id"])))
            if timing is not None:
                timing.start_module_abandon_ms += _start_elapsed_ms(t0)
            existing = None
        if existing:
            return UUID(str(existing["id"])), part
        t0 = perf_counter()
        row = speaking_repo.insert_speaking_attempt(
            user_id=user_id,
            mock_test_id=mock_test_id,
            mock_attempt_id=mock_attempt_id,
            part=part,
        )
        if timing is not None:
            timing.start_module_insert_ms += _start_elapsed_ms(t0)
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
    owner_row = _assert_mock_attempt_owner(
        mock_attempt_id=mock_attempt_id, user_id=user_id
    )
    snapshot = read_unlock_snapshot(mock_attempt_id=mock_attempt_id, user_id=user_id)
    if snapshot is not None:
        _validate_unlock_from_snapshot(
            snapshot=snapshot,
            mock_test_id=mock_test_id,
            module=module,
            part=part,
        )
        return

    modules = repo.list_mock_modules(mock_test_id)
    module_attempts = repo.list_module_attempts(mock_attempt_id)
    unlock = build_unlock_snapshot(
        mock_test_id=mock_test_id,
        modules=modules,
        module_attempts=module_attempts,
        current_module=owner_row.get("current_module"),
    )
    _validate_unlock_from_snapshot(
        snapshot=unlock,
        mock_test_id=mock_test_id,
        module=module,
        part=part,
    )
    write_unlock_snapshot_cache(
        mock_attempt_id=mock_attempt_id,
        user_id=user_id,
        unlock=unlock,
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
    invalidate_prefix(f"mock_session:v2:{user_id}:")
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


def _apply_mock_attempt_patch(
    bundle: dict[str, Any], patch: dict[str, Any]
) -> dict[str, Any]:
    """Apply mock_attempts UPDATE fields in-memory so finalize skips a refetch."""
    merged = dict(bundle)
    row = dict(merged.get("mock_attempt") or {})
    row.update(patch)
    merged["mock_attempt"] = row
    return merged


def _finalize_mock_progress_after_submit(
    *,
    mock_attempt_id: UUID,
    mock_test_id: UUID,
    user_id: UUID,
    invalidate_history: bool = False,
    timing: MockProgressTiming | None = None,
    bundle: dict[str, Any] | None = None,
    mock_attempt_patch: dict[str, Any] | None = None,
) -> MockAttemptProgress:
    """Cache warm after mock_attempt row updates.

    Overwrites progress/session Redis keys directly (SETEX) instead of
    DELETE-then-SET. When ``bundle`` is passed from ``on_module_attempt_completed``,
    skip the second ``get_mock_attempt_progress`` fetch and apply
    ``mock_attempt_patch`` in memory instead.
    """
    t_finalize = perf_counter()

    if invalidate_history:
        schedule_mock_history_cache_invalidation(
            user_id=user_id, mock_test_id=mock_test_id
        )

    if bundle is None:
        t0 = perf_counter()
        bundle = repo.fetch_mock_attempt_progress_bundle(
            mock_attempt_id=mock_attempt_id, user_id=user_id
        )
        if timing is not None:
            timing.progress_finalize_fetch_bundle_ms = _elapsed_ms(t0)
            timing.progress_fetch_bundle_count += 1
    elif mock_attempt_patch:
        bundle = _apply_mock_attempt_patch(bundle, mock_attempt_patch)

    if not bundle:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock attempt not found.")
    t0 = perf_counter()
    progress = _progress_from_bundle(bundle, user_id=user_id)
    row = bundle["mock_attempt"]
    unlock = build_unlock_snapshot(
        mock_test_id=mock_test_id,
        modules=list(bundle.get("modules") or []),
        module_attempts=list(bundle.get("module_attempts") or []),
        current_module=row.get("current_module"),
    )
    if timing is not None:
        timing.progress_finalize_compute_ms = _elapsed_ms(t0)

    t0 = perf_counter()
    write_progress_cache(
        mock_attempt_id=mock_attempt_id,
        user_id=user_id,
        mock_test_id=mock_test_id,
        progress=progress,
        unlock=unlock,
        timing=timing,
    )
    refresh_mock_in_progress_cache(
        user_id=user_id,
        mock_test_id=mock_test_id,
        mock_attempt_id=mock_attempt_id,
        status=str(row.get("status") or "in_progress"),
        current_module=row.get("current_module"),
    )
    if timing is not None:
        timing.progress_finalize_write_cache_ms = _elapsed_ms(t0)
        timing.progress_finalize_ms = _elapsed_ms(t_finalize)
    return progress


def on_module_attempt_completed(
    *,
    test_attempt_id: UUID,
    user_id: UUID,
    attempt: dict[str, Any] | None = None,
    timing: MockProgressTiming | None = None,
) -> MockAttemptProgress | None:
    """After module submit: advance mock_attempt or unlock next module."""
    t_progress = perf_counter()
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

    t0 = perf_counter()
    bundle = repo.fetch_mock_attempt_progress_bundle(
        mock_attempt_id=mock_attempt_id, user_id=user_id
    )
    if timing is not None:
        timing.progress_fetch_bundle_ms = _elapsed_ms(t0)
        timing.progress_fetch_bundle_count += 1

    if not bundle:
        return None
    modules = list(bundle.get("modules") or [])
    module_attempts = list(bundle.get("module_attempts") or [])

    t0 = perf_counter()
    parts_incomplete = not _module_parts_complete(
        mock_test_id=mock_test_id,
        module=module,
        module_attempts=module_attempts,
    )
    if parts_incomplete:
        parts = _required_attempt_parts(mock_test_id, module)
        done = {
            int(a["part"])
            for a in module_attempts
            if a.get("module") == module
            and a.get("status") == "completed"
            and a.get("part") is not None
        }
        remaining = [p for p in parts if p not in done]
        if timing is not None:
            timing.progress_parts_check_ms = _elapsed_ms(t0)
        if remaining:
            patch = {"current_module": module}
            t0 = perf_counter()
            repo.update_mock_attempt(
                mock_attempt_id=mock_attempt_id,
                fields=patch,
            )
            if timing is not None:
                timing.progress_update_mock_attempt_ms = _elapsed_ms(t0)
            result = _finalize_mock_progress_after_submit(
                mock_attempt_id=mock_attempt_id,
                mock_test_id=mock_test_id,
                user_id=user_id,
                timing=timing,
                bundle=bundle,
                mock_attempt_patch=patch,
            )
            if timing is not None:
                timing.progress_ms = _elapsed_ms(t_progress)
            return result
    elif timing is not None:
        timing.progress_parts_check_ms = _elapsed_ms(t0)

    mod_order = [str(m["module"]) for m in enabled_modules_in_catalog_order(modules)]
    try:
        idx = mod_order.index(module)
    except ValueError:
        idx = -1

    if idx >= 0 and idx < len(mod_order) - 1:
        next_mod = mod_order[idx + 1]
        patch = {"current_module": next_mod}
        t0 = perf_counter()
        repo.update_mock_attempt(
            mock_attempt_id=mock_attempt_id,
            fields=patch,
        )
        if timing is not None:
            timing.progress_update_mock_attempt_ms = _elapsed_ms(t0)
        result = _finalize_mock_progress_after_submit(
            mock_attempt_id=mock_attempt_id,
            mock_test_id=mock_test_id,
            user_id=user_id,
            timing=timing,
            bundle=bundle,
            mock_attempt_patch=patch,
        )
        if timing is not None:
            timing.progress_ms = _elapsed_ms(t_progress)
        return result

    patch = {
        "status": "completed",
        "completed_at": datetime.now(UTC).isoformat(),
        "current_module": None,
    }
    t0 = perf_counter()
    repo.update_mock_attempt(
        mock_attempt_id=mock_attempt_id,
        fields=patch,
    )
    if timing is not None:
        timing.progress_update_mock_attempt_ms = _elapsed_ms(t0)
    result = _finalize_mock_progress_after_submit(
        mock_attempt_id=mock_attempt_id,
        mock_test_id=mock_test_id,
        user_id=user_id,
        invalidate_history=True,
        timing=timing,
        bundle=bundle,
        mock_attempt_patch=patch,
    )
    if timing is not None:
        timing.progress_ms = _elapsed_ms(t_progress)
    return result
