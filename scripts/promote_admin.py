"""Shim: admin scripts live in admin/scripts/. Run from backend as before."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

_TARGET = Path(__file__).resolve().parents[2] / "admin" / "scripts" / "promote_admin.py"
if not _TARGET.is_file():
    raise SystemExit(f"Missing admin script: {_TARGET}")
# Keep cwd/backend imports working; execute target as __main__
sys.argv[0] = str(_TARGET)
runpy.run_path(str(_TARGET), run_name="__main__")
