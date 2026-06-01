# Phase 1A — Local Supabase (fast dev database)

Remote Supabase (`https://*.supabase.co`) adds **hundreds of ms per query** from your machine. Local Supabase runs Postgres + PostgREST on **127.0.0.1**, so `POST /api/mock-attempts` and module `start`/`submit` typically drop from **~8–10s to &lt;1–2s**.

## Prerequisites

1. **Docker Desktop** — running
2. **Supabase CLI** — `brew install supabase/tap/supabase`
3. **Backend venv** — `pip install -r requirements.txt`

## Quick start

From `backend/`:

```bash
chmod +x scripts/local_supabase.sh   # once
./scripts/local_supabase.sh start    # first run pulls images (~2–5 min)
```

This will:

1. Start local Supabase (API `http://127.0.0.1:54321`, Studio `http://127.0.0.1:54323`)
2. Apply all SQL files in `supabase/migrations/`
3. Write **`backend/.env.local`** with local URL + service role key (overrides cloud URLs in `.env`)

Then:

```bash
source .venv/bin/activate
python scripts/verify_schema.py
uvicorn app.main:app --reload --port 8000
# Confirm log: redis=ok  and  supabase_url=http://127.0.0.1:54321
```

Restart **Next.js** after first `start` if the frontend caches env at boot.

Optional: copy local URL/keys into `frontend/.env.local`:

```env
NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:54321
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<anon key from supabase status>
```

## Commands

| Command | Purpose |
|---------|---------|
| `./scripts/local_supabase.sh start` | Start stack + sync `.env.local` |
| `./scripts/local_supabase.sh reset` | Wipe DB + re-apply all migrations |
| `./scripts/local_supabase.sh status` | URLs, Studio, keys |
| `./scripts/local_supabase.sh sync` | Refresh `.env.local` from running stack |
| `./scripts/local_supabase.sh stop` | Stop containers |
| `./scripts/local_supabase.sh cloud` | Remove `.env.local` → use remote `.env` again |

## Switch back to cloud Supabase

```bash
./scripts/local_supabase.sh cloud
# Restart uvicorn — uses backend/.env remote keys only
```

Your cloud `.env` is never modified.

## Verify speed (Phase 0)

1. Run one Test 1 flow (dashboard → start mock → listening start).
2. Compare API log `duration_ms` vs when using remote Supabase.
3. Use `/dev/test1` → warm session ×2 (2nd call should be fast with Redis).

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `Docker is not running` | Start Docker Desktop |
| `supabase: command not found` | `brew install supabase/tap/supabase` |
| API still hits `*.supabase.co` | Ensure `.env.local` exists; restart uvicorn; check startup diagnostics |
| `verify_schema.py` missing tables | `./scripts/local_supabase.sh reset` |
| Port 54321 in use | `supabase stop` or change ports in `supabase/config.toml` |

## What stays on cloud

- **Redis (Upstash)** — optional; still used for read caches
- **R2** — listening audio presigns (keys in `.env`)
- **Google OAuth / Resend** — unchanged

Local DB has **no** production user data. Sign up / Google login again against local API.
