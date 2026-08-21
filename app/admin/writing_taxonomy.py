"""Admin Writing exam-module + Task 1 type taxonomy (Phase 3).

``practice_sets.exam_module`` values:
  academic | general_training | both

``both`` means the set is valid for Academic AND General Training consumers.
It does NOT mean content is duplicated.

Question types:
  task1_academic | task1_general | task2
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.practice.writing_track import (
    VALID_SET_EXAM_MODULES,
    normalize_set_exam_module,
)

VALID_WRITING_QUESTION_TYPES = frozenset(
    {"task1_academic", "task1_general", "task2"}
)

# Explicit admin classification only — never infer from title/slug/prompt.
SET_EXAM_MODULE_VALUES = tuple(sorted(VALID_SET_EXAM_MODULES))


def normalize_writing_question_type(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in VALID_WRITING_QUESTION_TYPES:
        return text
    return None


def default_writing_question_type(part: int) -> str:
    return "task1_academic" if int(part) == 1 else "task2"


def assert_valid_exam_module(value: object, *, required: bool = True) -> str | None:
    """Validate set-level exam_module. Returns normalized value or None if optional empty."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "exam_module is required for Writing sets.",
                    "code": "exam_module_required",
                },
            )
        return None
    normalized = normalize_set_exam_module(value)
    if normalized is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={
                "message": (
                    "exam_module must be one of: academic, general_training, both."
                ),
                "code": "exam_module_invalid",
            },
        )
    return normalized


def assert_valid_writing_question_type(
    value: object,
    *,
    part: int,
) -> str:
    raw = (str(value).strip() if value is not None else "") or ""
    if not raw:
        return default_writing_question_type(part)
    normalized = normalize_writing_question_type(raw)
    if normalized is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={
                "message": (
                    "question_type must be one of: "
                    "task1_academic, task1_general, task2."
                ),
                "code": "question_type_invalid",
            },
        )
    if part == 1 and normalized == "task2":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Task 1 cannot use question_type task2.",
                "code": "question_type_part_mismatch",
            },
        )
    if part == 2 and normalized in {"task1_academic", "task1_general"}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Task 2 cannot use a Task 1 question_type.",
                "code": "question_type_part_mismatch",
            },
        )
    return normalized


def writing_task_exam_module_compatible(
    *,
    question_type: object,
    exam_module: object,
) -> bool:
    """True when Task 1 type and set exam_module are a valid pair.

    Task 2 is compatible with academic, general_training, and both.
    """
    q_type = normalize_writing_question_type(question_type)
    set_mod = normalize_set_exam_module(exam_module)
    if q_type is None or set_mod is None:
        return False
    if q_type == "task2":
        return True
    if q_type == "task1_academic":
        return set_mod in {"academic", "both"}
    if q_type == "task1_general":
        return set_mod in {"general_training", "both"}
    return False


def assert_writing_task_exam_module_compatible(
    *,
    question_type: object,
    exam_module: object,
) -> None:
    if writing_task_exam_module_compatible(
        question_type=question_type,
        exam_module=exam_module,
    ):
        return
    q_type = normalize_writing_question_type(question_type) or str(question_type)
    set_mod = normalize_set_exam_module(exam_module) or str(exam_module)
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        detail={
            "message": (
                f"Invalid combination: question_type={q_type} with "
                f"exam_module={set_mod}."
            ),
            "code": "writing_taxonomy_mismatch",
        },
    )


def writing_taxonomy_publish_blockers(
    *,
    exam_module: object,
    question_types: list[Any],
    has_prompt: bool,
) -> list[str]:
    """Writing-specific publish blockers for exam_module + task types."""
    blockers: list[str] = []
    set_mod = normalize_set_exam_module(exam_module)
    if set_mod is None:
        blockers.append(
            "Writing: exam_module is required "
            "(academic, general_training, or both)."
        )
        return blockers

    if not has_prompt:
        # Caller may already add the prompt blocker; keep taxonomy separate.
        pass

    for raw in question_types:
        q_type = normalize_writing_question_type(raw)
        if q_type is None and raw not in (None, ""):
            blockers.append(
                f"Writing: invalid question_type {raw!r} "
                "(allowed: task1_academic, task1_general, task2)."
            )
            continue
        if q_type is None:
            continue
        if not writing_task_exam_module_compatible(
            question_type=q_type,
            exam_module=set_mod,
        ):
            blockers.append(
                f"Writing: question_type {q_type} is incompatible with "
                f"exam_module {set_mod}."
            )
    return blockers
