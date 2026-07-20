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

# Build deduplicated bind port list
BIND_PORTS="$PRIMARY_PORT"
add_bind_port() {
  port="$1"
  case " $BIND_PORTS " in
    *" $port "*) ;;
    *) BIND_PORTS="$BIND_PORTS $port" ;;
  esac
}

# Railway public domain Target Port is often 8000 while injected PORT is 8080 — bind both (+ primary).
if [ "$ON_RAILWAY" = "true" ]; then
  add_bind_port 8000
  add_bind_port 8080
fi

echo "[bandforge-api] railway=${ON_RAILWAY} PORT=${PORT:-unset} API_PORT=${API_PORT:-unset} bind=${BIND_PORTS}" >&2

WORKERS="${WEB_CONCURRENCY:-2}"
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

for port in $BIND_PORTS; do
  set -- "$@" --bind "${HOST}:${port}"
done

exec "$@"
