from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, Request, status
from jose import JWTError

from app.auth.constants import ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE
from app.auth.jwt import decode_access_token
from app.auth.schemas import SessionUser, UserPublic
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


async def _resolve_user_id_from_request(
    request: Request,
    bf_access: str | None,
) -> UUID:
    token = _extract_access_token(request, bf_access)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")
    try:
        payload = decode_access_token(token)
        return UUID(str(payload["sub"]))
    except (JWTError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token.") from exc


async def get_current_user(
    request: Request,
    bf_access: Annotated[str | None, Cookie(alias=ACCESS_TOKEN_COOKIE)] = None,
) -> UserPublic:
    user_id = await _resolve_user_id_from_request(request, bf_access)
    return await service.get_user_by_id(user_id)


async def get_current_session_user(
    request: Request,
    bf_access: Annotated[str | None, Cookie(alias=ACCESS_TOKEN_COOKIE)] = None,
) -> SessionUser:
    user_id = await _resolve_user_id_from_request(request, bf_access)
    return await service.get_session_user_by_id(user_id)


async def get_current_user_timed(
    request: Request,
    bf_access: Annotated[str | None, Cookie(alias=ACCESS_TOKEN_COOKIE)] = None,
) -> UserPublic:
    """Like get_current_user; stores auth_ms on request.state for route timing logs."""
    t0 = perf_counter()
    user = await get_current_user(request, bf_access)
    request.state.auth_ms = round((perf_counter() - t0) * 1000, 2)
    return user


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
