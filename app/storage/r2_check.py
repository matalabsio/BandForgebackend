"""R2 connectivity check (upload + presigned URL HEAD)."""

from __future__ import annotations

import io
from typing import Any

import boto3
import httpx
from botocore.config import Config

from app.config import Settings, get_settings
from app.storage.r2 import generate_signed_url

HEALTH_CHECK_KEY = "health-check/test.txt"
HEALTH_CHECK_BODY = b"bandforge-r2-health-check"


def r2_settings_ok(settings: Settings) -> tuple[bool, str | None]:
    if not settings.r2_access_key_id or not settings.r2_secret_access_key:
        return False, "R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY are required in backend/.env"
    endpoint = settings.r2_endpoint_url
    if not endpoint and settings.r2_account_id:
        endpoint = f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    if not endpoint:
        return False, "R2_ENDPOINT_URL or R2_ACCOUNT_ID is required in backend/.env"
    return True, None


def _s3_client(settings: Settings):
    endpoint = settings.r2_endpoint_url
    if not endpoint and settings.r2_account_id:
        endpoint = f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def run_r2_check() -> dict[str, Any]:
    """
    Upload a probe object, mint a presigned URL, and HEAD it.
    Returns a result dict; callers map failures to exit 1 / HTTP 503.
    """
    settings = get_settings()
    configured, hint = r2_settings_ok(settings)
    if not configured:
        return {
            "r2_configured": False,
            "upload_ok": False,
            "signed_url_ok": False,
            "bucket": settings.r2_bucket_name,
            "hint": hint,
        }

    upload_ok = False
    signed_url_ok = False
    signed_url: str | None = None
    errors: list[str] = []

    try:
        client = _s3_client(settings)
        client.put_object(
            Bucket=settings.r2_bucket_name,
            Key=HEALTH_CHECK_KEY,
            Body=io.BytesIO(HEALTH_CHECK_BODY),
            ContentType="text/plain",
        )
        upload_ok = True
    except Exception as exc:  # noqa: BLE001
        errors.append(f"upload: {exc}")

    if upload_ok:
        try:
            signed_url = generate_signed_url(HEALTH_CHECK_KEY, expiry=10800)
            with httpx.Client(timeout=15.0, trust_env=False) as http:
                # Presigned get_object URLs are for GET; HEAD often returns 403 on R2.
                response = http.get(signed_url)
            signed_url_ok = response.status_code == 200
            if not signed_url_ok:
                errors.append(f"signed_url GET returned {response.status_code}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"signed_url: {exc}")

    return {
        "r2_configured": True,
        "upload_ok": upload_ok,
        "signed_url_ok": signed_url_ok,
        "bucket": settings.r2_bucket_name,
        "key": HEALTH_CHECK_KEY,
        "signed_url_sample": (signed_url[:80] + "…") if signed_url and len(signed_url) > 80 else signed_url,
        "hint": "; ".join(errors) if errors else None,
    }
