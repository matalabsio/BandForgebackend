#!/usr/bin/env bash
# Always-on leased worker for practice.catalog_changed (Question Bank publish fan-out).
# The API process enqueues into practice_jobs; this process claims and fills empty days.
set -euo pipefail
export PYTHONPATH="${PYTHONPATH:-.}"
exec python -m app.practice.catalog_jobs
