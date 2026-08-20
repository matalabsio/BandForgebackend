"""Upload IELTS Listening audio to Cloudflare R2.

Presets:
  ielts-day3 (default) — 20 clips: listening/ielts-day3/part-<N>/q-<M>.mp3
  greenfield           — 4 clips:  listening/greenfield/part-<N>/full.mp3
  m03                  — 4 clips:  listening/m03/part-<N>/full.mp3 from mocktest/MT3/LT

Usage::

    cd backend
    python -m scripts.upload_listening_audio --preset ielts-day3
    python -m scripts.upload_listening_audio --preset greenfield
    python -m scripts.upload_listening_audio --preset m03
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
    "bandforge-s2": {
        "source": REPO_ROOT / "audio_seed" / "bandforge-s2",
        "key_prefix": "listening/bandforge-s2",
        "mode": "full_part",
    },
    "bandforge-s3": {
        "source": REPO_ROOT / "audio_seed" / "bandforge-s3",
        "key_prefix": "listening/bandforge-s3",
        "mode": "full_part",
    },
    "bandforge-s4": {
        "source": REPO_ROOT / "audio_seed" / "bandforge-s4",
        "key_prefix": "listening/bandforge-s4",
        "mode": "full_part",
    },
    "m01": {
        "source": REPO_ROOT / "audio_seed" / "m01",
        "key_prefix": "listening/m01",
        "mode": "full_part",
    },
    "m02": {
        "source": REPO_ROOT / "audio_seed" / "m02",
        "key_prefix": "listening/m02",
        "mode": "full_part",
    },
    "m03": {
        "source": REPO_ROOT.parent / "mocktest" / "MT3" / "LT",
        "key_prefix": "listening/m03",
        "mode": "named_files",
        "files": {
            1: "ElevenLabs_MT3_LT_T1.mp3",
            2: "ElevenLabs_MT3_LT_S2.mp3",
            3: "ElevenLabs_MT3_LT_S3.mp3",
            4: "ElevenLabs_MT_3_LT_S4.mp3",
        },
    },
    "m04": {
        "source": REPO_ROOT.parent / "mocktest" / "MT4" / "LT",
        "key_prefix": "listening/m04",
        "mode": "named_files",
        "files": {
            1: "ElevenLabs_MT4_LT_S1.mp3",
            2: "ElevenLabs_MT4_LT_S2.mp3",
            3: "ElevenLabs_MT4_LT_S3.mp3",
            4: "ElevenLabs_MT4_LT_S4.mp3",
        },
    },
    "m05": {
        "source": REPO_ROOT.parent / "mocktest" / "MT5" / "LT",
        "key_prefix": "listening/m05",
        "mode": "named_files",
        "files": {
            1: "ElevenLabs_MT5_LT_S1.mp3",
            2: "ElevenLabs_MT5_LT_S2.mp3",
            3: "ElevenLabs_MT5_LT_S3.mp3",
            4: "ElevenLabs_MT5_LT_S4.mp3",
        },
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


def upload_full_part_set(source: Path, key_prefix: str, *, dry_run: bool = False) -> int:
    client, bucket = _build_client()
    uploaded = 0
    missing: list[str] = []
    for part in (1, 2, 3, 4):
        local = source / f"part-{part}" / "full.mp3"
        key = f"{key_prefix}/part-{part}/full.mp3"
        if _upload_file(client, bucket, local, key, dry_run=dry_run):
            uploaded += 1
        else:
            missing.append(str(local))

    if missing:
        print(
            f"\nMissing {len(missing)} full-part file(s):",
            *[f"  - {m}" for m in missing],
            sep="\n",
            file=sys.stderr,
        )

    return uploaded


def upload_named_files(
    source: Path,
    key_prefix: str,
    files: dict[int, str],
    *,
    dry_run: bool = False,
) -> int:
    client, bucket = _build_client()
    uploaded = 0
    missing: list[str] = []
    for part, filename in sorted(files.items()):
        local = source / filename
        key = f"{key_prefix}/part-{part}/full.mp3"
        if _upload_file(client, bucket, local, key, dry_run=dry_run):
            uploaded += 1
        else:
            missing.append(str(local))

    if missing:
        print(
            f"\nMissing {len(missing)} named file(s):",
            *[f"  - {m}" for m in missing],
            sep="\n",
            file=sys.stderr,
        )

    return uploaded


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
        count = upload_full_part_set(source, key_prefix, dry_run=args.dry_run)
    elif preset["mode"] == "named_files":
        files = {int(k): str(v) for k, v in dict(preset["files"]).items()}  # type: ignore[arg-type]
        count = upload_named_files(source, key_prefix, files, dry_run=args.dry_run)
    else:
        count = upload_grid(source, key_prefix, dry_run=args.dry_run)

    print(f"\nDone. {count} object(s) {'would be' if args.dry_run else ''} uploaded.")


if __name__ == "__main__":
    main()
