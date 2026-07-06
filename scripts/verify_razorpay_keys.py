#!/usr/bin/env python3
"""Verify Razorpay API keys in backend/.env against the live API."""

from __future__ import annotations

import sys

from app.config import reload_settings
from app.payments.razorpay_client import clear_client_cache, probe_credentials


def main() -> int:
    reload_settings()
    clear_client_cache()
    ok, msg = probe_credentials()
    kid = reload_settings().razorpay_key_id or ""
    prefix = f"{kid[:18]}..." if kid else "(unset)"
    if ok:
        print(f"PASS — Razorpay credentials OK ({prefix})")
        return 0
    print(f"FAIL — {msg} ({prefix})")
    print(
        "Regenerate matching Test mode keys: Dashboard → Account & Settings → "
        "API Keys → Generate Key. Copy Key ID + Secret together into backend/.env, "
        "then restart uvicorn."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
