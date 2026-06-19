#!/usr/bin/env python3
"""Create or update a super_admin user (email + password) for admin dashboard access."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth.security import hash_password
from app.auth.utils import utcnow
from app.db.supabase_client import get_supabase

DEFAULT_ADMIN_EMAIL = "product@matalabs.io"


def bootstrap_admin_user(
    *,
    email: str,
    password: str,
    full_name: str = "Product Admin",
    role: str = "super_admin",
) -> UUID:
    sb = get_supabase()
    normalized = email.lower().strip()
    now = utcnow().isoformat()
    password_hash = hash_password(password)

    existing = (
        sb.table("users")
        .select("id, email")
        .eq("email", normalized)
        .limit(1)
        .execute()
    )

    if existing.data:
        user_id = str(existing.data[0]["id"])
        sb.table("users").update(
            {
                "password_hash": password_hash,
                "full_name": full_name,
                "role": role,
                "is_active": True,
                "email_verified_at": now,
                "updated_at": now,
            }
        ).eq("id", user_id).execute()
        print(f"OK: updated {normalized} → {role}")
        return UUID(user_id)

    inserted = (
        sb.table("users")
        .insert(
            {
                "email": normalized,
                "full_name": full_name,
                "password_hash": password_hash,
                "role": role,
                "is_active": True,
                "email_verified_at": now,
                "updated_at": now,
            }
        )
        .execute()
    )
    if not inserted.data:
        raise RuntimeError("Could not create admin user.")

    user_id = UUID(str(inserted.data[0]["id"]))
    print(f"OK: created {normalized} → {role}")
    return user_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--email",
        default=DEFAULT_ADMIN_EMAIL,
        help=f"Admin email (default: {DEFAULT_ADMIN_EMAIL})",
    )
    parser.add_argument("--password", required=True, help="Login password")
    parser.add_argument("--full-name", default="Product Admin")
    parser.add_argument(
        "--role",
        choices=["admin", "super_admin"],
        default="super_admin",
    )
    args = parser.parse_args()

    try:
        bootstrap_admin_user(
            email=args.email,
            password=args.password,
            full_name=args.full_name,
            role=args.role,
        )
    except Exception as exc:  # noqa: BLE001 — CLI
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
