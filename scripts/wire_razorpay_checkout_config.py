#!/usr/bin/env python3
"""Wire RAZORPAY_CHECKOUT_CONFIG_ID into backend/.env (Test or Live).

Usage:
  PYTHONPATH=. .venv/bin/python scripts/wire_razorpay_checkout_config.py config_XXXXXXXX

Dashboard steps (Test Mode) before running:
  1. Account & Settings → Payment Methods → ensure UPI enabled
  2. Checkout Features → Flash checkout OFF
  3. Payment Configuration → create BandForge UPI-first config
     (UPI Apps/Intent + UPI QR + Cards + Netbanking + Wallets; hide Pay Later)
  4. Save as Default; copy Configuration ID (config_…)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
KEY = "RAZORPAY_CHECKOUT_CONFIG_ID"


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].startswith("config_"):
        print(
            "Usage: PYTHONPATH=. .venv/bin/python "
            "scripts/wire_razorpay_checkout_config.py config_XXXXXXXX",
            file=sys.stderr,
        )
        return 2

    config_id = sys.argv[1].strip()
    # Razorpay rejects IDs that are not exactly 21 chars (e.g. config_ + 14).
    if not re.fullmatch(r"config_[A-Za-z0-9]{14}", config_id) or len(config_id) != 21:
        print(
            "Invalid Configuration ID. Expected exactly 21 chars "
            "(config_ + 14 alphanumerics) from Dashboard → Payment Configuration. "
            "Do not use placeholders like config_XXXXXXXX.",
            file=sys.stderr,
        )
        return 2
    if set(config_id[7:]) <= set("Xx"):
        print(
            "Refusing placeholder config_XXXXXXXX — paste the real Dashboard ID.",
            file=sys.stderr,
        )
        return 2

    if not ENV_PATH.is_file():
        print(f"Missing {ENV_PATH}", file=sys.stderr)
        return 1

    text = ENV_PATH.read_text()
    pattern = re.compile(rf"^{re.escape(KEY)}=.*$", re.M)
    line = f"{KEY}={config_id}"
    if pattern.search(text):
        text = pattern.sub(line, text)
    else:
        text = text.rstrip() + f"\n{line}\n"
    ENV_PATH.write_text(text)
    print(f"Updated {ENV_PATH.name}: {KEY}={config_id[:12]}…")
    print("Restart uvicorn fully, then run: scripts/diagnose_razorpay_checkout.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
