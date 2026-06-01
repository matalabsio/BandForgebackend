# Docker — production API (EC2 / ECS)

Run **bandforge-api** in a container behind nginx/Caddy on EC2. The frontend stays on Vercel; only this backend image runs on the server.

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage Python 3.12 image, non-root user, gunicorn + uvicorn workers |
| `docker-compose.yml` | Production service (`restart: unless-stopped`, healthcheck) |
| `docker-compose.dev.yml` | Optional local container with `--reload` |
| `.env.docker.example` | Template for EC2 `.env` |
| `requirements-prod.txt` | Runtime deps only (no pytest) |

## Quick start (EC2)

```bash
cd backend
cp .env.docker.example .env   # fill real Supabase, JWT, Redis, R2, Google, Resend
docker compose up -d --build
curl -fsS http://127.0.0.1:8000/health
```

Expected: `{"status":"ok"}`. Logs should show `env_local_active=False` and `redis=ok` (or `redis=off` if `REDIS_URL` empty).

## Environment

Compose loads `backend/.env`. Required for a real deployment:

- `SUPABASE_URL`, `SUPABASE_SECRET_KEY`
- `JWT_SECRET`, `JWT_REFRESH_SECRET` (or only `JWT_SECRET` if you use one)
- `FRONTEND_URL` — production Vercel URL (CORS)
- `REDIS_URL` — Upstash in the **same region** as EC2
- `GOOGLE_*`, `RESEND_*`, `R2_*` as needed

Optional tuning:

| Variable | Default | Notes |
|----------|---------|--------|
| `WEB_CONCURRENCY` | `2` | Gunicorn workers; ~2× CPU cores max |
| `API_PUBLISH_PORT` | `8000` | Host port mapped to container |
| `GUNICORN_TIMEOUT` | `120` | Long listening submits |
| `CORS_ORIGINS` | — | Comma-separated extra origins (staging) |

**Do not** mount or copy `.env.local` on EC2. With `APP_ENV=production`, local Supabase overrides are ignored.

## TLS on the host (recommended)

Expose container port **8000** only on `127.0.0.1`. Put reverse proxy on EC2:

```nginx
# /etc/nginx/sites-available/bandforge-api
server {
    listen 443 ssl http2;
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Vercel `NEXT_PUBLIC_API_URL` → `https://api.yourdomain.com`.

## Deploy / update

```bash
git pull
docker compose build --pull
docker compose up -d
docker compose ps
docker compose logs -f --tail=100 api
```

## Dev container (optional)

```bash
docker compose -f docker-compose.dev.yml up --build
```

Uses `UVICORN_RELOAD=1` and mounts `./app` read-only.

## Health

- Container: `GET /health` → `200` `{"status":"ok"}`
- Compose and Dockerfile `HEALTHCHECK` use the same endpoint.

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Container exits immediately | `docker compose logs api` — missing `SUPABASE_*` in `.env` |
| `redis=error` | `REDIS_URL` TLS (`rediss://`) and security group / Upstash allowlist |
| CORS errors from browser | Rare with Vercel BFF; set `FRONTEND_URL` + `CORS_ORIGINS` |
| Slow API | Supabase region ≠ EC2 region; fix co-location |
