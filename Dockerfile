# bandforge-api — production image for AWS EC2 / ECS / any Docker host
# Build:  docker build -t bandforge-api:latest .
# Run:    docker compose up -d

FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt .
RUN pip install --prefix=/install -r requirements-prod.txt


FROM python:3.12-slim-bookworm AS runtime

# Do not bake API_PORT here — it would shadow Railway's runtime PORT.
# Entrypoint binds to PORT, then API_PORT, then 8000.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    APP_ENV=production \
    API_HOST=0.0.0.0 \
    WEB_CONCURRENCY=2 \
    GUNICORN_TIMEOUT=120 \
    GUNICORN_GRACEFUL_TIMEOUT=30 \
    GUNICORN_KEEPALIVE=5

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

COPY --from=builder /install /usr/local
COPY app ./app
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Fail the image build if the app cannot import (catches missing prod deps early).
RUN SUPABASE_URL=https://build.invalid.supabase.co \
    SUPABASE_SECRET_KEY=build-only-not-for-runtime \
    JWT_SECRET=build-only-jwt-secret-min-32-chars \
    python -c "import app.main; print('import ok')"

RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && chown -R app:app /app

USER app

# Railway injects PORT at runtime (often 8080). Do not hardcode EXPOSE to 8000.
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD sh -c 'curl -fsS "http://127.0.0.1:${PORT:-${API_PORT:-8000}}/health"' || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
