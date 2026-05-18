from urllib.parse import urlparse

import boto3
from botocore.config import Config

from app.config import get_settings


def generate_signed_url(key: str, expiry: int = 10800) -> str:
    """Return a presigned GET URL for an object in the speaking-audio R2 bucket."""
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

    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.r2_bucket_name, "Key": key},
        ExpiresIn=expiry,
    )


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
