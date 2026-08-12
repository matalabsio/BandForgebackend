"""Short-lived HMAC tickets so the browser can PUT audio to Railway, not Vercel/R2."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import HTTPException, Request, status

from app.config import get_settings

TICKET_TTL_SEC = 900


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def mint_audio_upload_ticket(
    *,
    key: str,
    admin_id: str,
    size_bytes: int,
) -> str:
    payload = {
        "k": key,
        "a": str(admin_id),
        "s": int(size_bytes),
        "exp": int(time.time()) + TICKET_TTL_SEC,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    secret = get_settings().jwt_secret.encode("utf-8")
    sig = hmac.new(secret, raw, hashlib.sha256).digest()
    return f"{_b64url_encode(raw)}.{_b64url_encode(sig)}"


def parse_audio_upload_ticket(ticket: str) -> dict[str, Any]:
    try:
        blob, sig = (ticket or "").split(".", 1)
        raw = _b64url_decode(blob)
        expected = hmac.new(
            get_settings().jwt_secret.encode("utf-8"),
            raw,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected, _b64url_decode(sig)):
            raise ValueError("bad signature")
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired upload ticket.",
        ) from exc
    if int(payload.get("exp") or 0) < int(time.time()):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Upload ticket expired. Get a new one and retry.",
        )
    return payload


def public_api_origin(request: Request) -> str:
    settings = get_settings()
    explicit = (getattr(settings, "public_api_url", "") or "").strip().rstrip("/")
    if explicit:
        if not explicit.startswith("http"):
            explicit = f"https://{explicit}"
        return explicit
    proto = (
        request.headers.get("x-forwarded-proto")
        or request.url.scheme
        or "https"
    ).split(",")[0].strip()
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or ""
    ).split(",")[0].strip()
    if host:
        return f"{proto}://{host}".rstrip("/")
    return str(request.base_url).rstrip("/")
