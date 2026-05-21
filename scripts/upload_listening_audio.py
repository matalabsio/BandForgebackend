"""Upload IELTS Listening audio to Cloudflare R2.

Presets:
  ielts-day3 (default) — 20 clips: listening/ielts-day3/part-<N>/q-<M>.mp3
  greenfield           — 1 clip:   listening/greenfield/part-1/full.mp3

Usage::

    cd backend
    python -m scripts.upload_listening_audio --preset ielts-day3
    python -m scripts.upload_listening_audio --preset greenfield
    python -m scripts.upload_listening_audio --preset ielts-day3 --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import boto3
from botocore.config import Config

from app.config import get_settings


REPO_ROOT = Path(__file__).resolve().parents[1]

PRESETS: dict[str, dict[str, Path | str]] = {
    "ielts-day3": {
        "source": REPO_ROOT / "audio_seed" / "ielts-day3",
        "key_prefix": "listening/ielts-day3",
        "mode": "grid",
    },
    "greenfield": {
        "source": REPO_ROOT / "audio_seed" / "greenfield",
        "key_prefix": "listening/greenfield",
        "mode": "full_part",
    },
}


def _build_client():
    settings = get_settings()
    if not settings.r2_access_key_id or not settings.r2_secret_access_key:
        raise SystemExit(
            "R2 credentials missing — set R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY"
        )

    endpoint = settings.r2_endpoint_url
    if not endpoint and settings.r2_account_id:
        endpoint = f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    if not endpoint:
        raise SystemExit("R2_ENDPOINT_URL or R2_ACCOUNT_ID is required")

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    ), settings.r2_bucket_name


def _upload_file(
    client,
    bucket: str,
    local: Path,
    key: str,
    *,
    dry_run: bool,
) -> bool:
    if not local.exists():
        return False
    print(f"[{'DRY' if dry_run else 'UP '}] {local} -> s3://{bucket}/{key}")
    if not dry_run:
        client.upload_file(
            Filename=str(local),
            Bucket=bucket,
            Key=key,
            ExtraArgs={"ContentType": "audio/mpeg"},
        )
    return True


def upload_grid(source: Path, key_prefix: str, *, dry_run: bool = False) -> int:
    client, bucket = _build_client()
    uploaded = 0
    missing: list[str] = []

    for part in (1, 2, 3, 4):
        for q in range(1, 6):
            local = source / f"part-{part}" / f"q-{q}.mp3"
            key = f"{key_prefix}/part-{part}/q-{q}.mp3"
            if _upload_file(client, bucket, local, key, dry_run=dry_run):
                uploaded += 1
            else:
                missing.append(str(local))

    if missing:
        print(
            f"\nMissing {len(missing)} clip(s):",
            *[f"  - {m}" for m in missing],
            sep="\n",
            file=sys.stderr,
        )

    return uploaded


def upload_greenfield(source: Path, key_prefix: str, *, dry_run: bool = False) -> int:
    client, bucket = _build_client()
    local = source / "part-1" / "full.mp3"
    key = f"{key_prefix}/part-1/full.mp3"
    if not _upload_file(client, bucket, local, key, dry_run=dry_run):
        print(f"\nMissing file: {local}", file=sys.stderr)
        return 0
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preset",
        choices=list(PRESETS.keys()),
        default="ielts-day3",
        help="Upload preset (default: ielts-day3)",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Override local source folder",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print actions without uploading."
    )
    args = parser.parse_args()

    preset = PRESETS[args.preset]
    source = args.source or Path(preset["source"])  # type: ignore[arg-type]
    key_prefix = str(preset["key_prefix"])

    if not source.is_dir():
        raise SystemExit(f"Source folder not found: {source}")

    if preset["mode"] == "full_part":
        count = upload_greenfield(source, key_prefix, dry_run=args.dry_run)
    else:
        count = upload_grid(source, key_prefix, dry_run=args.dry_run)

    print(f"\nDone. {count} object(s) {'would be' if args.dry_run else ''} uploaded.")


if __name__ == "__main__":
    main()
