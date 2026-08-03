"""Shim: admin scripts live in admin/scripts/. Run from backend as before."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_TARGET = Path(__file__).resolve().parents[2] / "admin" / "scripts" / "bootstrap_admin_user.py"
if not _TARGET.is_file():
    raise SystemExit(f"Missing admin script: {_TARGET}")
# Ensure backend/app imports resolve when runpy executes the admin script
sys.path.insert(0, str(_BACKEND))
sys.argv[0] = str(_TARGET)
runpy.run_path(str(_TARGET), run_name="__main__")
