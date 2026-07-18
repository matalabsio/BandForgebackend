#!/usr/bin/env python3
"""Poll backend/.env until RAZORPAY_CHECKOUT_CONFIG_ID looks like config_…, then diagnose.

Usage:
  PYTHONPATH=. .venv/bin/python scripts/await_razorpay_checkout_config.py
  # or after paste:
  PYTHONPATH=. .venv/bin/python scripts/wire_razorpay_checkout_config.py config_XXX
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
KEY = "RAZORPAY_CHECKOUT_CONFIG_ID"
# Razorpay requires exactly 21 chars; ignore placeholders like config_XXXXXXXX.
PATTERN = re.compile(rf"^{re.escape(KEY)}=(config_[A-Za-z0-9]{{14}})\s*$", re.M)


def read_id() -> str | None:
    if not ENV_PATH.is_file():
        return None
    m = PATTERN.search(ENV_PATH.read_text())
    return m.group(1) if m else None


def main() -> int:
    print(
        "Waiting for Dashboard Configuration ID in backend/.env "
        f"({KEY}=config_…).\n"
        "Dashboard: Test Mode → Account & Settings → Payment Configuration → "
        "BandForge UPI-first → Save as Default → copy config_…\n"
        "Then either paste into .env or run wire_razorpay_checkout_config.py.\n"
    )
    deadline = time.time() + 30 * 60
    while time.time() < deadline:
        cid = read_id()
        if cid and set(cid[7:]) <= set("Xx"):
            cid = None  # placeholder
        if cid:
            print(f"Detected {KEY}={cid[:12]}…")
            print("Run a full uvicorn restart, then:")
            print("  env -u HTTP_PROXY -u HTTPS_PROXY PYTHONPATH=. "
                  ".venv/bin/python scripts/diagnose_razorpay_checkout.py")
            print("  env -u HTTP_PROXY -u HTTPS_PROXY PYTHONPATH=. "
                  ".venv/bin/python scripts/probe_checkout_upi.py")
            return 0
        time.sleep(3)
    print("Timed out after 30 minutes — no config_… found.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
