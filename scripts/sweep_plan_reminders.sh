#!/usr/bin/env bash
# Enqueue learning.daily_reminder outbox rows (once per user per IST day).
# Schedule daily ~07:00 Asia/Kolkata. Delivery still requires the always-on
# notification worker: bash scripts/run_notification_worker.sh
set -euo pipefail
export PYTHONPATH="${PYTHONPATH:-.}"
exec python scripts/sweep_plan_reminders.py "$@"
