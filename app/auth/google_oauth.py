import logging
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.config import get_settings

logger = logging.getLogger(__name__)


def _google_token_error_message(status_code: int, body_text: str) -> str:
    try:
        import json

        body = json.loads(body_text)
        err = str(body.get("error", ""))
        desc = str(body.get("error_description", ""))
        if err == "invalid_client" or "client secret" in desc.lower():
            return (
                "Google Client Secret is incorrect. In Google Cloud Console open "
                "Credentials → BandForge Web → copy the Client secret into "
                "GOOGLE_CLIENT_SECRET in backend/.env, then restart the API."
            )
        if err == "redirect_uri_mismatch":
            return (
                "Redirect URI mismatch. Add exactly "
                "http://localhost:3000/api/auth/google/callback "
                "under Authorized redirect URIs in Google Cloud Console."
            )
        if desc:
            return desc
    except Exception:
        pass
    return "Google sign-in failed. Try again."


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def _google_configured() -> bool:
    s = get_settings()
    return bool(s.google_client_id and s.google_client_secret and s.google_redirect_uri)


def ensure_google_configured() -> None:
    s = get_settings()
    if not s.google_client_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "GOOGLE_CLIENT_ID is missing in backend/.env.",
        )
    if not s.google_client_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "GOOGLE_CLIENT_SECRET is empty in backend/.env. Paste the GOCSPX-… secret from Google Cloud Console, save the file, and restart uvicorn.",
        )
    if not s.google_redirect_uri:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "GOOGLE_REDIRECT_URI is missing in backend/.env.",
        )


def create_oauth_state(*, next_path: str) -> str:
    settings = get_settings()
    payload = {
        "next": next_path if next_path.startswith("/") else "/dashboard",
        "n": secrets.token_urlsafe(8),
        "type": "google_oauth",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def parse_oauth_state(state: str) -> str:
    settings = get_settings()
    try:
        payload = jwt.decode(
            state, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        if payload.get("type") != "google_oauth":
            raise JWTError("invalid type")
        nxt = payload.get("next", "/dashboard")
        return nxt if isinstance(nxt, str) and nxt.startswith("/") else "/dashboard"
    except JWTError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid OAuth state.") from exc


def build_google_authorization_url(*, state: str) -> str:
    settings = get_settings()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_userinfo(*, code: str) -> dict[str, Any]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=20.0) as client:
        token_res = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_res.status_code >= 400:
            logger.error("Google token error %s: %s", token_res.status_code, token_res.text[:300])
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                _google_token_error_message(token_res.status_code, token_res.text),
            )
        token_data = token_res.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Google did not return an access token.",
            )

        user_res = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_res.status_code >= 400:
            logger.error("Google userinfo error %s", user_res.status_code)
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Could not read your Google profile.",
            )
        return user_res.json()
