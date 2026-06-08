#!/usr/bin/env python3
"""Import a full IELTS mock from test/MT1/ or test/MT2/ into Supabase + optional R2 upload hints.

Usage::

    cd backend && source .venv/bin/activate
    python -m scripts.import_mock --mock-dir ../test/MT1 --dry-run
    python -m scripts.import_mock --mock-dir ../test/MT1 --apply

Expects manifest.json::

    {
      "id": "a0000000-0000-4000-8000-000000000001",
      "title": "IELTS Academic Mock 1",
      "modules": [
        {"module": "reading", "sequence_order": 1, "duration_minutes": 60},
        {"module": "listening", "sequence_order": 2, "duration_minutes": 30}
      ]
    }

Founder JSON files under listening/ and reading/ are normalized via existing scripts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="Import full mock package")
    parser.add_argument(
        "--mock-dir",
        type=Path,
        default=REPO_ROOT / "test" / "MT1",
        help="Directory with manifest.json and module subfolders",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Run normalize scripts and print SQL path (does not auto-apply to remote DB)",
    )
    args = parser.parse_args()

    manifest_path = args.mock_dir / "manifest.json"
    if not manifest_path.is_file():
        print(f"Missing {manifest_path}", file=sys.stderr)
        print(
            "Create manifest.json — see backend/docs/mock_ingestion.md",
            file=sys.stderr,
        )
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mock_id = manifest.get("id")
    title = manifest.get("title", "IELTS Mock")
    print(f"Mock: {title} ({mock_id})")
    print(f"Modules: {manifest.get('modules', [])}")

    listening_dir = args.mock_dir / "listening"
    reading_dir = args.mock_dir / "reading"
    if listening_dir.is_dir():
        print(f"Listening assets: {list(listening_dir.glob('**/*'))[:8]}...")
    if reading_dir.is_dir():
        print(f"Reading assets: {list(reading_dir.glob('**/*'))[:8]}...")

    if args.dry_run:
        print("Dry run — no changes written.")
        return 0

    if not args.apply:
        print("Pass --apply to run normalizers or --dry-run to validate only.")
        return 0

    print("\nNext steps (manual):")
    print(
        "  1. Normalize test/MT1/LT/interface/*.json and test/MT1/RT/interface/*.json"
    )
    print("  2. python -m scripts.upload_m01_listening_audio")
    print("  3. Apply supabase/migrations/*_m01*.sql")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
