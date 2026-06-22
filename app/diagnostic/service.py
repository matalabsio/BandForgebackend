"""Diagnostic guest session service."""

from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException, status

from app.auth.schemas import AuthResponse, UserPublic
from app.auth import service as auth_service
from app.db.supabase_client import get_supabase


async def create_guest_session(
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
    existing_user: UserPublic | None = None,
) -> tuple[AuthResponse, str]:
    """Mint JWT cookies for a diagnostic guest, or return tokens for an existing session."""
    if existing_user is not None:
        if existing_user.role != "guest":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Already signed in. Continue with your account or sign out first.",
            )
        access, refresh, _ = await auth_service.issue_session_tokens(
            user_id=existing_user.id,
            email=existing_user.email,
            phone=existing_user.phone,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        user = await auth_service.get_user_by_id(existing_user.id)
        return auth_service.build_auth_response(user, access), refresh

    sb = get_supabase()
    user_id = uuid4()
    result = (
        sb.table("users")
        .insert(
            {
                "id": str(user_id),
                "full_name": "Diagnostic Guest",
                "role": "guest",
            }
        )
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Could not create guest session.",
        )

    access, refresh, _ = await auth_service.issue_session_tokens(
        user_id=user_id,
        email=None,
        phone=None,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    user = await auth_service.get_user_by_id(user_id)
    return auth_service.build_auth_response(user, access), refresh
