from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import get_settings


@lru_cache(maxsize=1)
def _cached_s3_client(
    endpoint: str,
    access_key: str,
    secret_key: str,
):
    """Reused boto3 client. Creating a client per call is slow (TLS + signer init)."""
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def _resolve_endpoint(settings) -> str:
    endpoint = settings.r2_endpoint_url
    if not endpoint and settings.r2_account_id:
        endpoint = f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    if not endpoint:
        raise RuntimeError("R2_ENDPOINT_URL or R2_ACCOUNT_ID is required")
    return endpoint


def _s3_client():
    settings = get_settings()
    if not settings.r2_access_key_id or not settings.r2_secret_access_key:
        raise RuntimeError("R2 credentials are not configured")
    return _cached_s3_client(
        _resolve_endpoint(settings),
        settings.r2_access_key_id,
        settings.r2_secret_access_key,
    )


def object_exists(key: str) -> bool:
    """Return True if the object key exists in the configured R2 bucket."""
    return object_head(key) is not None


def object_head(
    key: str,
    *,
    raise_errors: bool = False,
) -> dict[str, int | str] | None:
    """Return object size and content type, or None if missing / not configured."""
    settings = get_settings()
    if not settings.r2_access_key_id or not settings.r2_secret_access_key:
        if raise_errors:
            raise RuntimeError("R2 credentials are not configured")
        return None
    client = _s3_client()
    try:
        meta = client.head_object(Bucket=settings.r2_bucket_name, Key=key)
        return {
            "size": int(meta.get("ContentLength") or 0),
            "content_type": str(meta.get("ContentType") or ""),
        }
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return None
        if raise_errors:
            raise RuntimeError(f"R2 head_object failed for {key}: {exc}") from exc
        return None
    except Exception as exc:
        if raise_errors:
            raise RuntimeError(f"R2 head_object failed for {key}: {exc}") from exc
        return None


def generate_signed_url(key: str, expiry: int = 10800) -> str:
    """Return a presigned GET URL for an object in the speaking-audio R2 bucket."""
    settings = get_settings()
    client = _s3_client()

    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.r2_bucket_name, "Key": key},
        ExpiresIn=expiry,
    )


def generate_presigned_put_url(
    key: str,
    *,
    content_type: str,
    expiry: int = 900,
) -> str:
    """Return a presigned PUT URL constrained to the declared MIME type."""
    settings = get_settings()
    client = _s3_client()
    return client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.r2_bucket_name,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=expiry,
    )


def get_object_stream(
    key: str,
    *,
    range_header: str | None = None,
) -> tuple[Any, dict[str, str], int]:
    """Stream an object from R2. Returns (body, response_headers, http_status)."""
    settings = get_settings()
    client = _s3_client()
    kwargs: dict[str, Any] = {"Bucket": settings.r2_bucket_name, "Key": key}
    if range_header:
        kwargs["Range"] = range_header
    try:
        obj = client.get_object(**kwargs)
    except Exception as exc:
        raise RuntimeError(f"R2 get_object failed for {key}: {exc}") from exc

    headers: dict[str, str] = {
        "Content-Type": str(obj.get("ContentType") or "audio/mpeg"),
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
    }
    if obj.get("ContentLength") is not None:
        headers["Content-Length"] = str(obj["ContentLength"])
    if obj.get("ContentRange"):
        headers["Content-Range"] = str(obj["ContentRange"])
    status = 206 if range_header and obj.get("ContentRange") else 200
    return obj["Body"], headers, status


def get_object_bytes(*, key: str) -> bytes:
    """Download full object bytes from R2 (for Whisper transcription)."""
    settings = get_settings()
    client = _s3_client()
    try:
        obj = client.get_object(Bucket=settings.r2_bucket_name, Key=key)
    except Exception as exc:
        raise RuntimeError(f"R2 get_object failed for {key}: {exc}") from exc
    body = obj.get("Body")
    if body is None:
        raise RuntimeError(f"R2 get_object returned no body for {key}")
    return body.read()


def upload_object(*, key: str, body: bytes, content_type: str) -> None:
    """Upload bytes to the configured R2 bucket."""
    settings = get_settings()
    if not settings.r2_access_key_id or not settings.r2_secret_access_key:
        raise RuntimeError("R2 credentials are not configured")

    endpoint = settings.r2_endpoint_url
    if not endpoint and settings.r2_account_id:
        endpoint = f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    if not endpoint:
        raise RuntimeError("R2_ENDPOINT_URL or R2_ACCOUNT_ID is required")

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )
    client.put_object(
        Bucket=settings.r2_bucket_name,
        Key=key,
        Body=body,
        ContentType=content_type,
    )


def delete_object(key: str) -> None:
    settings = get_settings()
    if not settings.r2_access_key_id or not settings.r2_secret_access_key:
        return
    endpoint = settings.r2_endpoint_url
    if not endpoint and settings.r2_account_id:
        endpoint = f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    if not endpoint:
        return
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )
    try:
        client.delete_object(Bucket=settings.r2_bucket_name, Key=key)
    except Exception:
        pass


def parse_r2_object_url(url: str) -> str | None:
    """Extract object key from a public or path-style R2 URL, if possible."""
    parsed = urlparse(url)
    path = parsed.path.lstrip("/")
    if not path:
        return None
    settings = get_settings()
    if path.startswith(f"{settings.r2_bucket_name}/"):
        return path[len(settings.r2_bucket_name) + 1 :]
    return path
