#!/bin/sh
set -eu

HOST="0.0.0.0"

ON_RAILWAY=false
if [ -n "${RAILWAY_SERVICE_ID:-}" ] || [ -n "${RAILWAY_ENVIRONMENT:-}" ] || [ -n "${RAILWAY_PROJECT_ID:-}" ]; then
  ON_RAILWAY=true
fi

# PORT (Railway) → API_PORT → 8000
if [ -n "${PORT:-}" ]; then
  PRIMARY_PORT="$PORT"
elif [ -n "${API_PORT:-}" ]; then
  PRIMARY_PORT="$API_PORT"
else
  PRIMARY_PORT=8000
fi

# Bind only the port Railway/proxy expects. Extra 8000/8080 binds used to
# confuse healthchecks and look like a 1–2 minute crash loop.
echo "[bandforge-api] railway=${ON_RAILWAY} PORT=${PORT:-unset} API_PORT=${API_PORT:-unset} bind=${PRIMARY_PORT}" >&2

WORKERS="${WEB_CONCURRENCY:-1}"
TIMEOUT="${GUNICORN_TIMEOUT:-120}"
GRACEFUL="${GUNICORN_GRACEFUL_TIMEOUT:-30}"
KEEPALIVE="${GUNICORN_KEEPALIVE:-5}"

# Dev override: single worker with reload (compose profile dev only)
if [ "${APP_ENV:-production}" = "development" ] && [ "${UVICORN_RELOAD:-0}" = "1" ]; then
  exec uvicorn app.main:app \
    --host "$HOST" \
    --port "$PRIMARY_PORT" \
    --reload \
    --proxy-headers \
    --forwarded-allow-ips='*'
fi

set -- gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers "$WORKERS" \
  --timeout "$TIMEOUT" \
  --graceful-timeout "$GRACEFUL" \
  --keep-alive "$KEEPALIVE" \
  --forwarded-allow-ips='*' \
  --access-logfile - \
  --error-logfile - \
  --capture-output

set -- "$@" --bind "${HOST}:${PRIMARY_PORT}"

exec "$@"
