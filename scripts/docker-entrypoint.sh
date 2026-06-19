#!/bin/sh
set -eu

HOST="${API_HOST:-0.0.0.0}"
# Empty API_PORT is ignored; Railway injects PORT at runtime.
BIND_PORT="${API_PORT:-${PORT:-8000}}"
WORKERS="${WEB_CONCURRENCY:-2}"
TIMEOUT="${GUNICORN_TIMEOUT:-120}"
GRACEFUL="${GUNICORN_GRACEFUL_TIMEOUT:-30}"
KEEPALIVE="${GUNICORN_KEEPALIVE:-5}"

# Dev override: single worker with reload (compose profile dev only)
if [ "${APP_ENV:-production}" = "development" ] && [ "${UVICORN_RELOAD:-0}" = "1" ]; then
  exec uvicorn app.main:app \
    --host "$HOST" \
    --port "$BIND_PORT" \
    --reload \
    --proxy-headers \
    --forwarded-allow-ips='*'
fi

exec gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers "$WORKERS" \
  --bind "${HOST}:${BIND_PORT}" \
  --timeout "$TIMEOUT" \
  --graceful-timeout "$GRACEFUL" \
  --keep-alive "$KEEPALIVE" \
  --access-logfile - \
  --error-logfile - \
  --capture-output
