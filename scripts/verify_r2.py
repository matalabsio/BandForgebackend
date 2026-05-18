#!/usr/bin/env python3
"""Smoke-check R2 credentials, bucket upload, and presigned URL access."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import reload_settings
from app.storage.r2_check import run_r2_check


def main() -> int:
    reload_settings()
    result = run_r2_check()

    if not result["r2_configured"]:
        print(f"FAIL  R2 not configured — {result.get('hint')}")
        return 1

    print(f"OK    R2 configured (bucket={result['bucket']})")

    if result["upload_ok"]:
        print(f"OK    upload {result['key']}")
    else:
        print(f"FAIL  upload — {result.get('hint')}")
        return 1

    if result["signed_url_ok"]:
        print("OK    presigned URL GET 200")
    else:
        print(f"FAIL  presigned URL — {result.get('hint')}")
        return 1

    print("\nR2 health check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
