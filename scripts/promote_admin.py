#!/usr/bin/env python3
"""Promote a user to admin or super_admin by email."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.supabase_client import get_supabase


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", help="User email address")
    parser.add_argument(
        "--role",
        choices=["admin", "super_admin"],
        default="super_admin",
    )
    args = parser.parse_args()

    sb = get_supabase()
    result = (
        sb.table("users")
        .select("id, email, role")
        .eq("email", args.email.lower().strip())
        .limit(1)
        .execute()
    )
    if not result.data:
        print(f"ERROR: No user found with email {args.email}")
        return 1

    row = result.data[0]
    sb.table("users").update({"role": args.role, "is_active": True}).eq(
        "id", row["id"]
    ).execute()
    print(f"OK: {row['email']} promoted to {args.role}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
