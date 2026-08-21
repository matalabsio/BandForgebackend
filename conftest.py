"""Pytest bootstrap — environment gates only (no product logic)."""

from __future__ import annotations

import sys

# Parenthesized multi-context `with (` requires Python 3.10+ (PEP 617).
# Project README: python3.11 -m venv .venv  # requires Python 3.10+
if sys.version_info < (3, 10):
    raise SystemExit(
        "BandForge backend tests require Python 3.10+.\n"
        f"Current interpreter: {sys.version.split()[0]} ({sys.executable})\n\n"
        "Use the project venv from backend/:\n"
        "  cd backend\n"
        "  source .venv/bin/activate   # or: python3.11 -m venv .venv && pip install -r requirements.txt\n"
        "  python -m pytest tests/security/ tests/practice/ tests/payments/\n\n"
        "Do not run bare `pytest` under pyenv/system Python 3.8 — that lacks fastapi "
        "and cannot parse modern test syntax."
    )

try:
    import fastapi  # noqa: F401
except ModuleNotFoundError as exc:
    raise SystemExit(
        "fastapi is not installed for this interpreter.\n"
        f"Current interpreter: {sys.executable}\n\n"
        "Activate backend/.venv and install deps:\n"
        "  cd backend && source .venv/bin/activate && pip install -r requirements.txt\n"
        "  python -m pytest ..."
    ) from exc
