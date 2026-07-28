"""Minimal admin stubs — full admin API was intentionally removed from this app."""

from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.config import get_settings

ADMIN_ROLES = frozenset({"admin", "super_admin"})


def is_admin_email_allowed(email: str | None) -> bool:
    allowed = (get_settings().admin_allowed_email or "").strip().lower()
    if not allowed or not email:
        return False
    return email.strip().lower() == allowed


async def require_admin(
    user: Annotated[UserPublic, Depends(get_current_user)],
) -> UserPublic:
    if user.role not in ADMIN_ROLES and not is_admin_email_allowed(user.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return user
