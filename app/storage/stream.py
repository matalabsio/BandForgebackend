"""Cloudflare Stream API helpers (direct upload + video status)."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings

STREAM_API_BASE = "https://api.cloudflare.com/client/v4"


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


def _credentials() -> tuple[str, str]:
    settings = get_settings()
    account_id = (settings.cloudflare_account_id or settings.r2_account_id or "").strip()
    token = (settings.cloudflare_api_token or "").strip()
    if not account_id or not token:
        raise StreamError(
            "Cloudflare Stream is not configured (CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN).",
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
