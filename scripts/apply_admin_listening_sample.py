"""Apply admin listening sample JSON to Supabase (scoped to one section).

Bypasses the admin HTTP API but mirrors ingest publish: normalize, replace
questions for mock+module+part, insert rows with audio_url.

Usage:
    cd backend && source .venv/bin/activate
    python -m scripts.apply_admin_listening_sample seed/admin_samples/listening_mini_test3.json
    python -m scripts.apply_admin_listening_sample seed/admin_samples/listening_mini_test3.json --smoke-config
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

from scripts.normalize_listening_mock import normalize

DEFAULT_TEST3_ID = "eb5d9416-da1f-411d-8bf9-07ae4dbc5014"


def _default_audio_key(mock_id: str, part: int) -> str:
    return f"listening/{mock_id}/part-{part}/full.mp3"


def _delete_scoped_questions(client, *, mock_id: str, part: int) -> None:
    existing = (
        client.table("questions")
        .select("id")
        .eq("mock_test_id", mock_id)
        .eq("module", "listening")
        .eq("part", part)
        .execute()
    ).data or []
    qids = [str(r["id"]) for r in existing]
    if qids:
        client.table("answers").delete().in_("question_id", qids).execute()
        client.table("question_versions").delete().in_("question_id", qids).execute()
    client.table("questions").delete().eq("mock_test_id", mock_id).eq(
        "module", "listening"
    ).eq("part", part).execute()


def _ensure_audio_in_r2(audio_key: str, *, upload: bool) -> None:
    from app.storage.r2 import object_exists, upload_object

    if object_exists(audio_key):
        print(f"OK R2 audio exists: {audio_key}")
        return
    if not upload:
        print(
            f"WARN: audio not in R2 at {audio_key}. "
            "Student playback may fail until you upload an MP3 (admin ingest or --upload-audio).",
            file=sys.stderr,
        )
        return
    # Minimal MPEG frame — enough for head_object / presign smoke tests.
    placeholder = b"\xff\xfb\x90\x00" + b"\x00" * 512
    upload_object(key=audio_key, body=placeholder, content_type="audio/mpeg")
    print(f"Uploaded placeholder audio to R2: {audio_key}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Admin listening interface JSON")
    parser.add_argument("--part", type=int, default=1)
    parser.add_argument("--mock-id", help="Override mock_test_id from JSON")
    parser.add_argument("--audio-key", help="R2 object key for all questions in this section")
    parser.add_argument(
        "--upload-audio",
        action="store_true",
        help="Upload placeholder MP3 to R2 if missing",
    )
    parser.add_argument(
        "--smoke-config",
        action="store_true",
        help="Set listening_parts=1 and reading_passages=1 on the mock",
    )
    args = parser.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    mock_id = args.mock_id or str(data.get("mock_test_id") or "").strip()
    if not mock_id:
        print("mock_test_id required in JSON or --mock-id", file=sys.stderr)
        return 1

    audio_key = args.audio_key or _default_audio_key(mock_id, args.part)
    payload = normalize(
        data,
        mock_id=mock_id,
        audio_key=audio_key,
        allow_unsupported=False,
        part=args.part,
        renumber_per_part=True,
    )
    rows = payload.get("questions") or []
    if not rows:
        print("No questions produced from JSON", file=sys.stderr)
        return 1

    from app.db.supabase_client import get_supabase

    client = get_supabase()
    mock_row = (
        client.table("mock_tests").select("id, title").eq("id", mock_id).limit(1).execute()
    ).data
    if not mock_row:
        print(f"MISSING: mock_tests row for {mock_id}", file=sys.stderr)
        return 1

    _ensure_audio_in_r2(audio_key, upload=args.upload_audio)
    _delete_scoped_questions(client, mock_id=mock_id, part=args.part)

    inserts = [
        {
            "mock_test_id": mock_id,
            "module": "listening",
            "question_type": row.get("question_type"),
            "question_number": int(row.get("question_number") or 1),
            "part": int(row.get("part") or args.part),
            "prompt": row.get("prompt"),
            "passage_text": row.get("passage_text"),
            "options": row.get("options"),
            "correct_answer": row.get("correct_answer"),
            "skill_tag": row.get("skill_tag"),
            "audio_url": row.get("audio_url"),
        }
        for row in rows
    ]
    client.table("questions").insert(inserts).execute()

    if args.smoke_config:
        client.table("mock_tests").update(
            {"listening_parts": 1, "reading_passages": 1}
        ).eq("id", mock_id).execute()
        print("Updated mock: listening_parts=1, reading_passages=1")

    print(
        f"Applied {len(inserts)} listening questions for {mock_row[0]['title']} "
        f"(part {args.part}, mock {mock_id})"
    )
    print(f"Verify: python -m scripts.verify_listening_mock --mock-id {mock_id} --min-questions 4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
