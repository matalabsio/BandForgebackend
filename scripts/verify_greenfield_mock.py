"""Check Greenfield listening mock exists in Supabase.

Usage:
    cd backend && source .venv/bin/activate
    python -m scripts.verify_greenfield_mock
"""

from __future__ import annotations

from app.listening.constants import LISTENING_TEST_ID as GREENFIELD_ID


def main() -> None:
    from app.db.supabase_client import get_supabase

    client = get_supabase()
    mock = (
        client.table("mock_tests")
        .select("id, title, is_published")
        .eq("id", GREENFIELD_ID)
        .limit(1)
        .execute()
    )
    rows = mock.data or []
    if not rows:
        print("MISSING: mock_tests row for Greenfield.")
        print("Fix: run backend/seed/greenfield_listening_part1_seed.sql in Supabase SQL Editor.")
        raise SystemExit(1)

    print(f"OK mock: {rows[0]['title']} (published={rows[0].get('is_published')})")

    qs = (
        client.table("questions")
        .select("id", count="exact")
        .eq("mock_test_id", GREENFIELD_ID)
        .eq("module", "listening")
        .execute()
    )
    count = qs.count if qs.count is not None else len(qs.data or [])
    if count < 10:
        print(f"WARN: only {count} listening questions (expected 10). Re-run seed SQL.")
        raise SystemExit(1)

    print(f"OK questions: {count} listening rows")
    print("Greenfield listening test is ready. Use:")
    print("  http://localhost:3000/test/listening")


if __name__ == "__main__":
    main()
