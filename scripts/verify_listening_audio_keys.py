"""Verify listening audio_url keys exist in Cloudflare R2.

Usage:
    cd backend && source .venv/bin/activate
    python -m scripts.verify_listening_audio_keys --preset m01
"""

from __future__ import annotations

import argparse
from collections import defaultdict

from app.db.supabase_client import get_supabase
from app.storage.r2 import object_exists, parse_r2_object_url


PRESET_IDS = {
    "m01": "a0000000-0000-4000-8000-000000000001",
}


def _object_key(raw: str) -> str:
    parsed = parse_r2_object_url(raw.strip())
    return parsed or raw.strip().lstrip("/")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preset",
        choices=sorted(PRESET_IDS.keys()),
        default="m01",
        help="Listening preset to verify.",
    )
    args = parser.parse_args()

    mock_test_id = PRESET_IDS[args.preset]
    client = get_supabase()
    result = (
        client.table("questions")
        .select("id, part, question_number, audio_url")
        .eq("mock_test_id", mock_test_id)
        .eq("module", "listening")
        .order("part")
        .order("question_number")
        .execute()
    )
    rows = list(result.data or [])
    if not rows:
        print(f"MISSING: no listening questions found for preset '{args.preset}'.")
        raise SystemExit(1)

    by_part_keys: dict[int, set[str]] = defaultdict(set)
    missing_keys: set[str] = set()
    missing_rows = 0

    for row in rows:
        part = int(row.get("part") or 1)
        audio_url = (row.get("audio_url") or "").strip()
        if not audio_url:
            missing_rows += 1
            continue
        key = _object_key(audio_url)
        by_part_keys[part].add(key)
        if not object_exists(key):
            missing_keys.add(key)

    if missing_rows:
        print(f"MISSING: {missing_rows} question rows have empty audio_url.")

    for part in sorted(by_part_keys.keys()):
        part_keys = sorted(by_part_keys[part])
        joined = ", ".join(part_keys)
        print(f"Part {part}: {joined}")

    if missing_keys:
        print("\nMISSING R2 OBJECTS:")
        for key in sorted(missing_keys):
            print(f"  - {key}")
        raise SystemExit(1)

    if missing_rows:
        raise SystemExit(1)

    print("\nOK: all configured listening audio_url keys exist in R2.")


if __name__ == "__main__":
    main()
