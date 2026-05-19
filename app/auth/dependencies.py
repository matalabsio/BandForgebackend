from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, Request, status
from jose import JWTError

from app.auth.constants import ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE
from app.auth.jwt import decode_access_token
from app.auth.schemas import UserPublic
from app.auth import service


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _extract_access_token(
    request: Request,
    bf_access: Annotated[str | None, Cookie(alias=ACCESS_TOKEN_COOKIE)] = None,
) -> str | None:
    return _extract_bearer(request) or bf_access


async def get_current_user(
    request: Request,
    bf_access: Annotated[str | None, Cookie(alias=ACCESS_TOKEN_COOKIE)] = None,
) -> UserPublic:
    token = _extract_access_token(request, bf_access)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")
    try:
        payload = decode_access_token(token)
        user_id = UUID(str(payload["sub"]))
    except (JWTError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token.") from exc
    return await service.get_user_by_id(user_id)


async def get_optional_user(
    request: Request,
    bf_access: Annotated[str | None, Cookie(alias=ACCESS_TOKEN_COOKIE)] = None,
) -> UserPublic | None:
    token = _extract_access_token(request, bf_access)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        return await service.get_user_by_id(UUID(str(payload["sub"])))
    except (JWTError, ValueError):
        return None


def get_refresh_token(
    bf_refresh: Annotated[str | None, Cookie(alias=REFRESH_TOKEN_COOKIE)] = None,
) -> str | None:
    return bf_refresh
