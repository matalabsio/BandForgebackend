#!/usr/bin/env python3
"""Deprecated wrapper — use evaluate_fixture.py --calibrate."""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "diagnostic_writing_calibration.py has been retired.\n"
        "Use:\n"
        "  python scripts/evaluate_fixture.py --all --calibrate\n"
        "  python scripts/evaluate_fixture.py --all --calibrate --prompt-version v5\n"
        "  python scripts/evaluate_fixture.py --all --live --calibrate --no-cache\n"
        "  python scripts/evaluate_fixture.py --all --calibrate --json-report /tmp/calib.json\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
