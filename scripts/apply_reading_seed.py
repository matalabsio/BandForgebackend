"""Apply founder reading JSON to Supabase (mock_tests + questions).

Usage:
    cd backend && source .venv/bin/activate
    python -m scripts.apply_reading_seed ../test/reading/interface/BandForge_Reading_T2_Interface_Data.json
    python -m scripts.apply_reading_seed ../test/reading/interface/BandForge_Reading_T3_Interface_Data.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.normalize_reading_mock import flatten_questions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    rows = flatten_questions(data)
    mock_id = rows[0]["mock_test_id"]
    title = rows[0]["title"]
    description = rows[0].get("description")

    from app.db.supabase_client import get_supabase

    client = get_supabase()

    # Remove dependent rows
    q_ids = (
        client.table("questions")
        .select("id")
        .eq("mock_test_id", mock_id)
        .execute()
    ).data or []
    for q in q_ids:
        client.table("answers").delete().eq("question_id", q["id"]).execute()
    client.table("questions").delete().eq("mock_test_id", mock_id).execute()
    attempts = (
        client.table("test_attempts").select("id").eq("mock_test_id", mock_id).execute()
    ).data or []
    for a in attempts:
        client.table("module_scores").delete().eq("attempt_id", a["id"]).execute()
    client.table("test_attempts").delete().eq("mock_test_id", mock_id).execute()

    client.table("mock_tests").upsert(
        {
            "id": mock_id,
            "title": title,
            "description": description,
            "is_published": True,
        }
    ).execute()

    payload = [
        {
            "mock_test_id": r["mock_test_id"],
            "module": "reading",
            "question_type": r["question_type"],
            "question_number": r["question_number"],
            "prompt": r["prompt"],
            "passage_text": r["passage_text"],
            "options": r["options"],
            "correct_answer": r["correct_answer"],
            "skill_tag": r["skill_tag"],
        }
        for r in rows
    ]
    client.table("questions").insert(payload).execute()
    print(f"Applied {len(payload)} questions for {mock_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
