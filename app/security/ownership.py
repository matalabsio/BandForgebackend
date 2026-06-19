"""Shared ownership checks — return 404 (not 403) to avoid resource enumeration."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status


def ensure_owner_or_not_found(
    record: dict[str, Any],
    user_id: UUID,
    *,
    user_field: str = "user_id",
) -> None:
    if str(record.get(user_field)) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found.",
        )
