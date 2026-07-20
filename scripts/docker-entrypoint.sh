#!/bin/sh
set -eu

# Railway routes public traffic to the port the app listens on ($PORT).
# Force 0.0.0.0 in container/cloud — binding localhost breaks the edge proxy (502).
if [ -n "${PORT:-}" ]; then
  HOST="0.0.0.0"
else
  HOST="${API_HOST:-0.0.0.0}"
fi

# PORT (Railway) → API_PORT (explicit override) → 8000 (local compose default).
if [ -n "${PORT:-}" ]; then
  BIND_PORT="$PORT"
elif [ -n "${API_PORT:-}" ]; then
  BIND_PORT="$API_PORT"
else
  BIND_PORT=8000
fi

ON_RAILWAY=false
if [ -n "${RAILWAY_SERVICE_ID:-}" ] || [ -n "${RAILWAY_ENVIRONMENT:-}" ] || [ -n "${RAILWAY_PROJECT_ID:-}" ]; then
  ON_RAILWAY=true
fi

echo "[bandforge-api] starting gunicorn on ${HOST}:${BIND_PORT} (PORT=${PORT:-unset} API_PORT=${API_PORT:-unset} railway=${ON_RAILWAY})" >&2

# Railway: healthcheck uses $PORT (often 8080) but public domain Target Port may be 8000.
# Bind both so internal health and public URL work without manual Target Port edits.
BIND_PUBLIC_8000=false
if [ "$ON_RAILWAY" = "true" ] && [ -n "${PORT:-}" ] && [ "$BIND_PORT" != "8000" ]; then
  BIND_PUBLIC_8000=true
  echo "[bandforge-api] Railway dual-bind: ${HOST}:${BIND_PORT} + ${HOST}:8000" >&2
fi

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

if [ "$BIND_PUBLIC_8000" = "true" ]; then
  exec gunicorn app.main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers "$WORKERS" \
    --bind "${HOST}:${BIND_PORT}" \
    --bind "${HOST}:8000" \
    --timeout "$TIMEOUT" \
    --graceful-timeout "$GRACEFUL" \
    --keep-alive "$KEEPALIVE" \
    --forwarded-allow-ips='*' \
    --access-logfile - \
    --error-logfile - \
    --capture-output
fi

exec gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers "$WORKERS" \
  --bind "${HOST}:${BIND_PORT}" \
  --timeout "$TIMEOUT" \
  --graceful-timeout "$GRACEFUL" \
  --keep-alive "$KEEPALIVE" \
  --forwarded-allow-ips='*' \
  --access-logfile - \
  --error-logfile - \
  --capture-output
