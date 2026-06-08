"""Upload M01 listening MP3s from test/MT1/LT/audio/ to R2.

Uses legacy object keys ``test/Listening_S{N}_Audio.mp3`` expected by Supabase.

Usage::

    cd backend && source .venv/bin/activate
    python -m scripts.upload_m01_listening_audio --dry-run
    python -m scripts.upload_m01_listening_audio
"""

from __future__ import annotations

import argparse
import sys

from scripts.test_content_paths import listening_audio_paths
from scripts.upload_listening_audio import _build_client, _upload_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client, bucket = _build_client()
    uploaded = 0
    missing: list[str] = []

    for part, local, key in listening_audio_paths():
        if _upload_file(client, bucket, local, key, dry_run=args.dry_run):
            uploaded += 1
            print(f"Part {part}: OK")
        else:
            missing.append(str(local))

    if missing:
        print("\nMissing local files:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 1

    print(f"\nDone. {uploaded} object(s) {'would be' if args.dry_run else ''} uploaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
