"""Check listening content is available for practice / academic mocks.

Usage:
    cd backend && source .venv/bin/activate
    python -m scripts.verify_greenfield_mock
"""

from __future__ import annotations

from app.mock_catalog.constants import (
    ACADEMIC_M01_MOCK_TEST_ID,
    M01_MOCK_TEST_ID,
)

# Legacy greenfield Part 1 seed id (may be reused for diagnostic).
GREENFIELD_LEGACY_ID = "d0000000-0000-4000-8000-000000000001"


def main() -> None:
    from app.db.supabase_client import get_supabase

    client = get_supabase()

    print(f"Catalog Test 1 (M01) id: {M01_MOCK_TEST_ID}")
    m01 = (
        client.table("mock_tests")
        .select("id, title, is_published")
        .eq("id", M01_MOCK_TEST_ID)
        .limit(1)
        .execute()
    )
    m01_rows = m01.data or []
    if m01_rows:
        print(f"  → {m01_rows[0]['title']} (published={m01_rows[0].get('is_published')})")
    else:
        print("  → MISSING mock_tests row")

    m01_qs = (
        client.table("questions")
        .select("id", count="exact")
        .eq("mock_test_id", M01_MOCK_TEST_ID)
        .eq("module", "listening")
        .execute()
    )
    m01_count = m01_qs.count if m01_qs.count is not None else len(m01_qs.data or [])
    print(f"  → listening questions: {m01_count}")
    if m01_count == 0:
        print(
            "  NOTE: Catalog Test 1 is speaking-only. Plan listening for bank hubs "
            "must open /practice/listening/{hubId}/exercise (not /test/1/listening)."
        )

    academic = (
        client.table("mock_tests")
        .select("id, title, is_published")
        .eq("id", ACADEMIC_M01_MOCK_TEST_ID)
        .limit(1)
        .execute()
    )
    ac_rows = academic.data or []
    if ac_rows:
        ac_qs = (
            client.table("questions")
            .select("id", count="exact")
            .eq("mock_test_id", ACADEMIC_M01_MOCK_TEST_ID)
            .eq("module", "listening")
            .execute()
        )
        ac_count = ac_qs.count if ac_qs.count is not None else len(ac_qs.data or [])
        print(
            f"OK academic M01: {ac_rows[0]['title']} "
            f"(published={ac_rows[0].get('is_published')}, listening={ac_count})"
        )
    else:
        print(f"MISSING: academic mock {ACADEMIC_M01_MOCK_TEST_ID}")

    gf = (
        client.table("questions")
        .select("id", count="exact")
        .eq("mock_test_id", GREENFIELD_LEGACY_ID)
        .eq("module", "listening")
        .execute()
    )
    gf_count = gf.count if gf.count is not None else len(gf.data or [])
    print(f"Legacy greenfield id listening questions: {gf_count}")

    if ac_rows and ac_count >= 10:
        print("Listening content is available on academic M01.")
        print("Bank-hub plan practice: /practice/listening/{hubId}/exercise")
        return

    if gf_count >= 10:
        print("Legacy greenfield listening rows present.")
        return

    print("WARN: no usable listening question set found.")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
