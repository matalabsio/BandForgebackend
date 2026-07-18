#!/usr/bin/env bash
# Hourly reconcile cron entrypoint (Railway cron service or external scheduler).
# Exits non-zero on apply errors so the cron platform can alert.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="${PYTHONPATH:-.}"

HOURS="${RECONCILE_HOURS:-48}"
PYTHON_BIN="${PYTHON_BIN:-python}"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
fi

exec "$PYTHON_BIN" scripts/reconcile_payments.py --hours "$HOURS" --apply
