"""Token gate for intern assessment APIs."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, status

from app.intern import repository


def intern_token_from_header(
    x_intern_token: Annotated[str | None, Header()] = None,
) -> str:
    token = (x_intern_token or "").strip()
    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Intern assessment token required.",
        )
    return token


def get_intern_application(
    token: Annotated[str, Depends(intern_token_from_header)],
) -> dict[str, Any]:
    row = repository.get_by_token(token)
    if not row:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired intern assessment token.",
        )
    return row
