#!/usr/bin/env python3
"""Enable / backfill / verify Tier 1 PII masking on a non-production database.

Usage (from backend/):
  python -m scripts.anonymize_tier1_pii --enable --backfill --verify --i-understand-nonprod

Requires SUPABASE_URL + SUPABASE_SECRET_KEY (or SERVICE_ROLE_KEY) from env / .env.
Optional DATABASE_URL is unused for RPC; connection is via Supabase service role.

Hard guard: refuses known production project refs unless PII_MASK_ALLOW_PROD=1
(and even then still requires --i-understand-nonprod). Prefer never setting that.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Allow running from repo root or backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db.supabase_client import get_supabase

# Default deny-list: production / primary cloud project for MATA-lab.
_DEFAULT_PROD_REFS = ("nkwtxkhtsclyakympbno",)

_MASKED_EMAIL_RE = re.compile(r"@masked\.local$", re.I)
_MASKED_PHONE_RE = re.compile(r"^\+9100\d{8}$")


def _project_ref_from_url(url: str) -> str | None:
    host = urlparse(url).hostname or ""
    # https://<ref>.supabase.co
    if host.endswith(".supabase.co"):
        return host.split(".")[0]
    return None


def _prod_refs() -> set[str]:
    refs = set(_DEFAULT_PROD_REFS)
    extra = os.environ.get("PII_MASK_PROD_PROJECT_REFS", "").strip()
    if extra:
        refs.update(r.strip() for r in extra.split(",") if r.strip())
    return refs


def _assert_nonprod(supabase_url: str, *, force_ack: bool) -> None:
    if not force_ack:
        raise SystemExit(
            "Refusing to run: pass --i-understand-nonprod "
            "(only for staging/local after a DB refresh)."
        )

    ref = _project_ref_from_url(supabase_url)
    allow_prod = os.environ.get("PII_MASK_ALLOW_PROD", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    local = os.environ.get("SUPABASE_LOCAL", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    host = urlparse(supabase_url).hostname or ""
    is_local_host = host in ("127.0.0.1", "localhost") or host.endswith(".local")

    if ref and ref in _prod_refs() and not allow_prod and not local and not is_local_host:
        raise SystemExit(
            f"Refusing to mask PII on production project ref {ref!r}.\n"
            "Point SUPABASE_URL at staging/local, or set PII_MASK_ALLOW_PROD=1 "
            "only with explicit ops approval (not recommended)."
        )


def _enable(sb: Any) -> None:
    now = datetime.now(timezone.utc).isoformat()
    result = (
        sb.table("pii_masking_config")
        .update({"enabled": True, "updated_at": now})
        .eq("id", 1)
        .execute()
    )
    if not result.data:
        sb.table("pii_masking_config").upsert(
            {"id": 1, "enabled": True, "updated_at": now}
        ).execute()
    print("OK  pii_masking_config.enabled = true")


def _disable(sb: Any) -> None:
    now = datetime.now(timezone.utc).isoformat()
    sb.table("pii_masking_config").update(
        {"enabled": False, "updated_at": now}
    ).eq("id", 1).execute()
    print("OK  pii_masking_config.enabled = false")


def _backfill(sb: Any) -> dict[str, Any]:
    result = sb.rpc("mask_tier1_pii_backfill").execute()
    data = result.data
    if isinstance(data, list) and data:
        data = data[0]
    print(f"OK  mask_tier1_pii_backfill → {data}")
    return data if isinstance(data, dict) else {"raw": data}


def _count_unmasked(sb: Any) -> dict[str, int]:
    """Count rows that still look like real Tier 1 contact data."""
    counts: dict[str, int] = {}

    users = (
        sb.table("users")
        .select("id,email,phone,full_name")
        .execute()
        .data
        or []
    )
    counts["users_unmasked"] = sum(
        1
        for u in users
        if (u.get("email") and not _MASKED_EMAIL_RE.search(str(u["email"])))
        or (u.get("phone") and not _MASKED_PHONE_RE.match(str(u["phone"])))
        or (u.get("full_name") and not str(u["full_name"]).startswith("Masked User "))
    )

    diags = (
        sb.table("diagnostic_review_submissions")
        .select("id,email,phone,full_name")
        .execute()
        .data
        or []
    )
    counts["diagnostic_unmasked"] = sum(
        1
        for d in diags
        if (d.get("email") and not _MASKED_EMAIL_RE.search(str(d["email"])))
        or (d.get("phone") and not _MASKED_PHONE_RE.match(str(d["phone"])))
        or (d.get("full_name") and not str(d["full_name"]).startswith("Masked User "))
    )

    leads = (
        sb.table("signup_leads")
        .select("id,email,phone,full_name")
        .execute()
        .data
        or []
    )
    counts["signup_leads_unmasked"] = sum(
        1
        for d in leads
        if (d.get("email") and not _MASKED_EMAIL_RE.search(str(d["email"])))
        or (d.get("phone") and not _MASKED_PHONE_RE.match(str(d["phone"])))
        or (d.get("full_name") and not str(d["full_name"]).startswith("Masked User "))
    )

    outbox = (
        sb.table("notification_outbox")
        .select("id,recipient_snapshot")
        .execute()
        .data
        or []
    )
    counts["outbox_unmasked"] = sum(
        1
        for r in outbox
        if r.get("recipient_snapshot")
        and not _MASKED_EMAIL_RE.search(str(r["recipient_snapshot"]))
        and not _MASKED_PHONE_RE.match(str(r["recipient_snapshot"]))
    )

    return counts


def _verify(sb: Any, *, fail_on_unmasked: bool) -> int:
    enabled = sb.rpc("pii_masking_is_enabled").execute().data
    print(f"OK  pii_masking_is_enabled → {enabled}")
    counts = _count_unmasked(sb)
    for key, value in counts.items():
        print(f"    {key}={value}")
    total = sum(counts.values())
    if total and fail_on_unmasked:
        print(f"FAIL verify: {total} unmasked Tier 1 contact row(s) remain")
        return 1
    if total:
        print(f"WARN verify: {total} unmasked Tier 1 contact row(s) remain")
    else:
        print("OK  verify: no unmasked Tier 1 contact fields found")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--i-understand-nonprod",
        action="store_true",
        help="Required acknowledgement that the target DB is non-production",
    )
    parser.add_argument("--enable", action="store_true", help="Set masking enabled=true")
    parser.add_argument("--disable", action="store_true", help="Set masking enabled=false")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Run mask_tier1_pii_backfill()",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Report unmasked contact counts (and exit 1 if any remain)",
    )
    args = parser.parse_args(argv)

    if not (args.enable or args.disable or args.backfill or args.verify):
        parser.error("Specify at least one of --enable/--disable/--backfill/--verify")

    settings = get_settings()
    _assert_nonprod(settings.supabase_url, force_ack=args.i_understand_nonprod)

    # Clear cached client if settings changed between runs in same process
    get_supabase.cache_clear()
    sb = get_supabase()

    if args.disable and args.enable:
        parser.error("Cannot pass both --enable and --disable")

    if args.disable:
        _disable(sb)

    if args.enable:
        _enable(sb)

    if args.backfill:
        _backfill(sb)

    if args.verify:
        return _verify(sb, fail_on_unmasked=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
