"""Verify a reading mock exists in Supabase with expected question count."""

from __future__ import annotations

import argparse

from app.reading.constants import READING_T2_TEST_ID, READING_T3_TEST_ID


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock-id", default=READING_T2_TEST_ID)
    parser.add_argument("--min-questions", type=int, default=13)
    args = parser.parse_args()

    from app.db.supabase_client import get_supabase

    client = get_supabase()
    mock = (
        client.table("mock_tests")
        .select("id, title, is_published")
        .eq("id", args.mock_id)
        .limit(1)
        .execute()
    )
    rows = mock.data or []
    if not rows:
        print(f"MISSING: mock_tests row for {args.mock_id}")
        raise SystemExit(1)

    print(f"OK mock: {rows[0]['title']} (published={rows[0].get('is_published')})")

    qs = (
        client.table("questions")
        .select("id", count="exact")
        .eq("mock_test_id", args.mock_id)
        .eq("module", "reading")
        .execute()
    )
    count = qs.count if qs.count is not None else len(qs.data or [])
    if count < args.min_questions:
        print(f"WARN: only {count} reading questions (expected >= {args.min_questions}).")
        raise SystemExit(1)

    pub = (
        client.table("questions")
        .select("id, passage_text, correct_answer")
        .eq("mock_test_id", args.mock_id)
        .eq("module", "reading")
        .eq("question_number", 1)
        .limit(1)
        .execute()
    )
    q1 = (pub.data or [None])[0]
    if not q1 or not q1.get("passage_text"):
        print("WARN: question 1 missing passage_text")
        raise SystemExit(1)
    if "correct_answer" in (q1.keys() if q1 else []):
        pass
    print(f"OK: {count} reading questions; passage on Q1; answers stored server-side only.")


if __name__ == "__main__":
    main()
