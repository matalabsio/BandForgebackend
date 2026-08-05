#!/usr/bin/env bash
# Always-on leased outbox worker (speaking.release + learning.daily_reminder).
# Plan reminder rows are enqueued by scripts/sweep_plan_reminders.sh (daily cron).
set -euo pipefail
export PYTHONPATH="${PYTHONPATH:-.}"
exec python -m app.notifications.worker
