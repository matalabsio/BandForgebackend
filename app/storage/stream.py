"""Cloudflare Stream API helpers (direct upload + video status)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from app.config import get_settings

STREAM_API_BASE = "https://api.cloudflare.com/client/v4"
_STREAM_UID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class StreamError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        cf_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.cf_code = cf_code


def normalize_customer_code(raw: str) -> str:
    value = (raw or "").strip()
    value = value.removeprefix("https://").removeprefix("http://")
    if ".cloudflarestream.com" in value:
        value = value.split(".cloudflarestream.com", 1)[0]
    return value.strip().strip("/")


def playback_iframe_url(*, customer_code: str, stream_uid: str) -> str:
    code = normalize_customer_code(customer_code)
    uid = (stream_uid or "").strip()
    if not code or not uid:
        return ""
    return f"https://{code}.cloudflarestream.com/{uid}/iframe"


def parse_stream_uid(raw: str) -> str:
    """Accept a raw Stream UID or a Cloudflare playback / watch URL."""
    value = unquote((raw or "").strip())
    if not value:
        raise StreamError("Stream UID is required.", status_code=400)
    if "://" in value or value.startswith("www."):
        parsed = urlparse(value if "://" in value else f"https://{value}")
        host = (parsed.hostname or "").lower()
        parts = [p for p in (parsed.path or "").split("/") if p]
        if host.endswith("cloudflarestream.com") and parts:
            if parts[0] in {"watch", "iframe"} and len(parts) > 1:
                value = parts[1]
            else:
                value = parts[0]
        elif parts:
            value = parts[0]
        value = value.split("?", 1)[0].strip()
    if value.lower() in {"iframe", "watch", "manifest", "thumbnails"}:
        raise StreamError("Could not read a Stream video UID from that URL.", status_code=400)
    if not _STREAM_UID_RE.match(value) or "." in value:
        raise StreamError(
            "Enter a Stream video UID or a cloudflarestream.com iframe / watch URL.",
            status_code=400,
        )
    return value


def _credentials() -> tuple[str, str]:
    settings = get_settings()
    account_id = (settings.cloudflare_account_id or "").strip()
    token = (settings.cloudflare_api_token or "").strip()
    if not account_id or not token:
        raise StreamError(
            "Cloudflare Stream is not configured on Railway. Set CLOUDFLARE_ACCOUNT_ID, "
            "CLOUDFLARE_API_TOKEN, and STREAM_CUSTOMER_CODE (Stream lives on a different "
            "account than R2).",
            status_code=503,
        )
    return account_id, token


def _raise_from_payload(payload: dict[str, Any], *, http_status: int) -> None:
    errors = payload.get("errors") or []
    messages = payload.get("messages") or []
    first = errors[0] if errors else (messages[0] if messages else {})
    cf_code = first.get("code") if isinstance(first, dict) else None
    text = ""
    if isinstance(first, dict):
        text = str(first.get("message") or "").strip()
    if not text:
        text = "Cloudflare Stream request failed."
    status_code = 409 if cf_code == 10011 else (502 if http_status >= 500 else 400)
    if cf_code == 10011:
        text = (
            "Stream storage quota is 0. Buy a Stream plan in the Cloudflare dashboard, "
            "then try uploading again."
        )
    raise StreamError(text, status_code=status_code, cf_code=cf_code if isinstance(cf_code, int) else None)


def create_direct_upload(
    *,
    title: str,
    max_duration_seconds: int = 3600,
    require_signed_urls: bool = False,
) -> dict[str, str]:
    """Basic one-time upload URL (files must be under ~200MB). Prefer create_tus_upload for larger files."""
    account_id, token = _credentials()
    duration = max(1, min(int(max_duration_seconds or 3600), 21600))
    url = f"{STREAM_API_BASE}/accounts/{account_id}/stream/direct_upload"
    body = {
        "maxDurationSeconds": duration,
        "meta": {"name": (title or "BandForge video").strip() or "BandForge video"},
        "requireSignedURLs": bool(require_signed_urls),
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
    except httpx.HTTPError as exc:
        raise StreamError(f"Could not reach Cloudflare Stream: {exc}", status_code=503) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise StreamError("Cloudflare Stream returned an invalid response.", status_code=502) from exc

    if not payload.get("success") or response.status_code >= 400:
        _raise_from_payload(payload if isinstance(payload, dict) else {}, http_status=response.status_code)

    result = payload.get("result") or {}
    uid = str(result.get("uid") or "").strip()
    upload_url = str(result.get("uploadURL") or "").strip()
    if not uid or not upload_url:
        raise StreamError("Cloudflare Stream did not return an upload URL.", status_code=502)
    return {"uid": uid, "uploadURL": upload_url}


def create_tus_upload(
    *,
    upload_length: int,
    title: str,
    max_duration_seconds: int = 3600,
    require_signed_urls: bool = False,
) -> dict[str, str]:
    """Provision a tus upload URL (required for files over 200MB; works for smaller too).

    Uses Cloudflare's ``?direct_user=true`` creator-upload flow so the browser can
    upload without seeing the API token.
    """
    account_id, token = _credentials()
    length = int(upload_length or 0)
    if length <= 0:
        raise StreamError("upload_length must be a positive integer.", status_code=400)
    duration = max(1, min(int(max_duration_seconds or 3600), 21600))
    name = (title or "BandForge video").strip() or "BandForge video"

    def _b64(value: str) -> str:
        import base64

        return base64.b64encode(value.encode("utf-8")).decode("ascii")

    meta_parts = [
        f"name {_b64(name)}",
        f"maxDurationSeconds {_b64(str(duration))}",
    ]
    if require_signed_urls:
        meta_parts.append("requiresignedurls")
    metadata = ",".join(meta_parts)

    url = f"{STREAM_API_BASE}/accounts/{account_id}/stream?direct_user=true"
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Tus-Resumable": "1.0.0",
                    "Upload-Length": str(length),
                    "Upload-Metadata": metadata,
                },
            )
    except httpx.HTTPError as exc:
        raise StreamError(f"Could not reach Cloudflare Stream: {exc}", status_code=503) from exc

    location = (response.headers.get("Location") or "").strip()
    media_id = (response.headers.get("stream-media-id") or "").strip()
    if response.status_code >= 400 or not location:
        try:
            payload = response.json()
        except ValueError:
            payload = {"errors": [{"message": response.text[:300] or "tus create failed"}]}
        _raise_from_payload(payload if isinstance(payload, dict) else {}, http_status=response.status_code)

    # Location may embed the uid; prefer stream-media-id header.
    uid = media_id
    if not uid:
        # Fallback: last path segment of Location
        uid = location.rstrip("/").rsplit("/", 1)[-1].split("?")[0].strip()
    if not uid:
        raise StreamError("Cloudflare Stream did not return a media id.", status_code=502)
    return {"uid": uid, "uploadURL": location}


def playback_signed_iframe_url(*, customer_code: str, token: str) -> str:
    """Iframe URL where the path segment is a signed JWT (not the raw video UID)."""
    code = normalize_customer_code(customer_code)
    tok = (token or "").strip()
    if not code or not tok:
        return ""
    return f"https://{code}.cloudflarestream.com/{tok}/iframe"


def create_signed_playback_token(
    stream_uid: str,
    *,
    ttl_seconds: int | None = None,
) -> str:
    """Mint a short-lived Stream playback token via Cloudflare ``/stream/{uid}/token``."""
    uid = (stream_uid or "").strip()
    if not uid:
        raise StreamError("Missing Stream video UID.", status_code=400)

    settings = get_settings()
    ttl = int(ttl_seconds or settings.stream_token_ttl_seconds or 3600)
    ttl = max(60, min(ttl, 86400))

    account_id, token = _credentials()
    url = f"{STREAM_API_BASE}/accounts/{account_id}/stream/{uid}/token"
    import time

    # Cloudflare expects absolute unix expiry for custom tokens.
    body: dict[str, Any] = {"exp": int(time.time()) + ttl}
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
    except httpx.HTTPError as exc:
        raise StreamError(f"Could not reach Cloudflare Stream: {exc}", status_code=503) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise StreamError("Cloudflare Stream returned an invalid response.", status_code=502) from exc

    if not payload.get("success") or response.status_code >= 400:
        _raise_from_payload(payload if isinstance(payload, dict) else {}, http_status=response.status_code)

    result = payload.get("result") or {}
    signed = str(result.get("token") or "").strip()
    if not signed:
        raise StreamError("Cloudflare Stream did not return a playback token.", status_code=502)
    return signed


def set_require_signed_urls(stream_uid: str, *, required: bool = True) -> None:
    """Ensure a Stream video cannot be played with a bare public UID."""
    account_id, token = _credentials()
    uid = (stream_uid or "").strip()
    if not uid:
        raise StreamError("Missing Stream video UID.", status_code=400)
    url = f"{STREAM_API_BASE}/accounts/{account_id}/stream/{uid}"
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"uid": uid, "requireSignedURLs": bool(required)},
            )
    except httpx.HTTPError as exc:
        raise StreamError(f"Could not reach Cloudflare Stream: {exc}", status_code=503) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise StreamError("Cloudflare Stream returned an invalid response.", status_code=502) from exc

    if not payload.get("success") or response.status_code >= 400:
        _raise_from_payload(payload if isinstance(payload, dict) else {}, http_status=response.status_code)


def get_video(stream_uid: str) -> dict[str, Any]:
    account_id, token = _credentials()
    uid = (stream_uid or "").strip()
    if not uid:
        raise StreamError("Missing Stream video UID.", status_code=400)
    url = f"{STREAM_API_BASE}/accounts/{account_id}/stream/{uid}"
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as exc:
        raise StreamError(f"Could not reach Cloudflare Stream: {exc}", status_code=503) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise StreamError("Cloudflare Stream returned an invalid response.", status_code=502) from exc

    if not payload.get("success") or response.status_code >= 400:
        _raise_from_payload(payload if isinstance(payload, dict) else {}, http_status=response.status_code)

    result = payload.get("result")
    return result if isinstance(result, dict) else {}


def delete_video(stream_uid: str) -> None:
    """Permanently delete a video from the Cloudflare Stream account."""
    account_id, token = _credentials()
    uid = (stream_uid or "").strip()
    if not uid:
        raise StreamError("Missing Stream video UID.", status_code=400)
    url = f"{STREAM_API_BASE}/accounts/{account_id}/stream/{uid}"
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.delete(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as exc:
        raise StreamError(f"Could not reach Cloudflare Stream: {exc}", status_code=503) from exc

    if response.status_code == 404:
        return
    try:
        payload = response.json()
    except ValueError as exc:
        if response.status_code < 400:
            return
        raise StreamError("Cloudflare Stream returned an invalid response.", status_code=502) from exc

    if isinstance(payload, dict) and payload.get("success"):
        return
    if response.status_code >= 400 or (isinstance(payload, dict) and not payload.get("success")):
        _raise_from_payload(payload if isinstance(payload, dict) else {}, http_status=response.status_code)


def list_account_videos(*, limit: int = 100) -> list[dict[str, Any]]:
    """List videos in the Cloudflare Stream account (not BandForge tags)."""
    account_id, token = _credentials()
    page_size = max(1, min(int(limit or 100), 1000))
    url = f"{STREAM_API_BASE}/accounts/{account_id}/stream"
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params={"limit": page_size},
            )
    except httpx.HTTPError as exc:
        raise StreamError(f"Could not reach Cloudflare Stream: {exc}", status_code=503) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise StreamError("Cloudflare Stream returned an invalid response.", status_code=502) from exc

    if not payload.get("success") or response.status_code >= 400:
        _raise_from_payload(payload if isinstance(payload, dict) else {}, http_status=response.status_code)

    result = payload.get("result")
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    return []
