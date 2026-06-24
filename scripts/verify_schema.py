#!/usr/bin/env python3
"""Smoke-check Supabase connectivity and Phase 2 table presence."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root or backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db.supabase_client import get_supabase

PHASE2_TABLES = (
    "questions",
    "test_attempts",
    "answers",
    "module_scores",
    "speaking_reviews",
)

ADMIN_TABLES = (
    "question_versions",
    "admin_audit_logs",
    "diagnostic_attempts",
    "diagnostic_review_submissions",
    "diagnostic_ai_evaluations",
)


PLACEHOLDER_HOSTS = ("your-project.supabase.co",)


def main() -> int:
    settings = get_settings()
    if any(host in settings.supabase_url for host in PLACEHOLDER_HOSTS):
        print(
            "ERROR: Supabase URL is still the .env.example placeholder.\n"
            "Restore backend/.env with NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SECRET_KEY\n"
            "from Supabase Dashboard → Settings → API.\n"
            "Do not run: cp .env.example .env  (that wipes real keys)."
        )
        return 1

    client = get_supabase()
    missing: list[str] = []

    for table in PHASE2_TABLES:
        try:
            client.table(table).select("id").limit(1).execute()
            print(f"OK  {table}")
        except Exception as exc:  # noqa: BLE001 — CLI diagnostic
            err = str(exc)
            if "nodename nor servname" in err or "Name or service not known" in err:
                print(f"MISSING or inaccessible: {table} (cannot resolve Supabase host — check .env URL)")
            else:
                print(f"MISSING or inaccessible: {table} ({exc})")
            missing.append(table)

    for table in ADMIN_TABLES:
        try:
            client.table(table).select("id").limit(1).execute()
            print(f"OK  {table}")
        except Exception as exc:  # noqa: BLE001 — CLI diagnostic
            print(f"MISSING or inaccessible: {table} ({exc})")
            missing.append(table)

    try:
        row = (
            client.table("users")
            .select("id, role, is_active")
            .limit(1)
            .execute()
        ).data
        if row is not None:
            print("OK  users.role + users.is_active")
    except Exception as exc:  # noqa: BLE001 — CLI diagnostic
        print(f"MISSING or inaccessible: users.role/is_active ({exc})")
        missing.append("users.role")

    try:
        client.table("mock_tests").select("id, status").limit(1).execute()
        print("OK  mock_tests.status")
    except Exception as exc:  # noqa: BLE001 — CLI diagnostic
        print(f"MISSING or inaccessible: mock_tests.status ({exc})")
        missing.append("mock_tests.status")

    if missing:
        print(
            "\nRun pending supabase/migrations (phase2 + admin foundation) "
            "in the Supabase SQL Editor if tables or columns are missing."
        )
        return 1

    print("\nAll Phase 2 + admin foundation schema checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
