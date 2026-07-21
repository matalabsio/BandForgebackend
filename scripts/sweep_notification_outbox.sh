#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="${PYTHONPATH:-.}"
exec python -m app.notifications.worker --once
