"""Check a listening mock exists in Supabase with expected question count.

Usage:
    cd backend && source .venv/bin/activate
    python -m scripts.verify_listening_mock --mock-id e0000000-0000-4000-8000-000000000002
    python -m scripts.verify_listening_mock  # defaults to Greenfield
"""

from __future__ import annotations

import argparse

from app.listening.constants import LISTENING_S2_TEST_ID, LISTENING_TEST_ID


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mock-id",
        default=LISTENING_TEST_ID,
        help="mock_tests.id to verify",
    )
    parser.add_argument(
        "--min-questions",
        type=int,
        default=10,
        help="Minimum listening question rows required",
    )
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
        print("Fix: run the matching seed SQL in Supabase SQL Editor.")
        raise SystemExit(1)

    print(f"OK mock: {rows[0]['title']} (published={rows[0].get('is_published')})")

    qs = (
        client.table("questions")
        .select("id", count="exact")
        .eq("mock_test_id", args.mock_id)
        .eq("module", "listening")
        .execute()
    )
    count = qs.count if qs.count is not None else len(qs.data or [])
    if count < args.min_questions:
        print(f"WARN: only {count} listening questions (expected >= {args.min_questions}).")
        raise SystemExit(1)

    print(f"OK questions: {count} listening rows")
    if args.mock_id == LISTENING_S2_TEST_ID:
        print("S2 listening mock is ready. Use:")
        print("  http://localhost:3000/test/listening?part=2")
    elif args.mock_id == LISTENING_TEST_ID:
        print("Greenfield listening mock is ready. Use:")
        print("  http://localhost:3000/test/listening?part=1")


if __name__ == "__main__":
    main()
