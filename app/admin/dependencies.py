"""Admin authorization dependencies."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import Depends, HTTPException, status

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.config import get_settings

AdminRole = Literal["admin", "super_admin"]

ADMIN_ROLES: frozenset[str] = frozenset({"admin", "super_admin"})

ADMIN_ACCESS_DENIED_DETAIL = "This account is not authorized for admin access."


def is_admin_email_allowed(email: str | None) -> bool:
    """Return True only when email matches ADMIN_ALLOWED_EMAIL (fail-closed if unset)."""
    allowed = get_settings().admin_allowed_email_normalized()
    if not allowed:
        return False
    return (email or "").strip().lower() == allowed


def _ensure_active(user: UserPublic) -> UserPublic:
    if not user.is_active:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )
    return user


def ensure_admin_access(user: UserPublic) -> UserPublic:
    _ensure_active(user)
    if user.role not in ADMIN_ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    if not is_admin_email_allowed(user.email):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=ADMIN_ACCESS_DENIED_DETAIL,
        )
    return user


async def require_admin(
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> UserPublic:
    return ensure_admin_access(current_user)


async def require_super_admin(
    current_user: Annotated[UserPublic, Depends(require_admin)],
) -> UserPublic:
    if current_user.role != "super_admin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Super admin access required.",
        )
    return current_user
