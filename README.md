# bandforge-api (backend)

FastAPI service for BandForge — question serving, test sessions, scoring, and async evaluation.

## Day 1 checklist

| Task | Status |
|------|--------|
| Supabase migration (Phase 1 + Phase 2 tables) | Done — verify with `python scripts/verify_schema.py` |
| FastAPI scaffold + `/health` + `/api/tests/*` | Done |
| Pydantic models (`app/models/`) | Done — stubs for Day 2 |
| Supabase client (`app/db/supabase_client.py`) | Done |
| R2 signed URL + health check | Done — `python scripts/verify_r2.py` or `GET /api/tests/r2-check` |

## Docker (production / EC2)

- **Step-by-step EC2 (Ubuntu):** **[docs/EC2_DEPLOYMENT.md](docs/EC2_DEPLOYMENT.md)**
- **Docker quick reference:** **[docs/DOCKER.md](docs/DOCKER.md)**

```bash
cp .env.docker.example .env   # edit secrets
docker compose up -d --build
curl -fsS http://127.0.0.1:8000/health
```

## Setup

```bash
cd backend
python3.11 -m venv .venv   # requires Python 3.10+
source .venv/bin/activate
pip install -r requirements.txt
```

### Running tests

Always use the project venv (Python **3.10+**). Bare `pytest` under pyenv/system Python 3.8 will fail collection (`ModuleNotFoundError: fastapi` / `app`, and `SyntaxError` on parenthesized `with (` blocks).

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/security/ tests/practice/ tests/payments/
```

Or without activating:

```bash
cd backend
.venv/bin/python -m pytest tests/security/ tests/practice/ tests/payments/
```

Copy env **only if you do not already have** `backend/.env`:

```bash
cp .env.example .env   # then edit with real Supabase keys
```

**Do not** run `cp .env.example .env` if `.env` already exists — it overwrites your keys with placeholders and breaks `verify_schema.py` (DNS error on `your-project.supabase.co`).

Required in `.env` (aliases supported):

- `NEXT_PUBLIC_SUPABASE_URL` or `SUPABASE_URL`
- `SUPABASE_SECRET_KEY` (service role / secret key for server-side API)

Optional for R2:

- `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET_NAME` (default `bandforge-speaking-audio`)
- `R2_ENDPOINT_URL`

## Local Supabase (Phase 1A — recommended for dev speed)

See **[docs/LOCAL_SUPABASE.md](docs/LOCAL_SUPABASE.md)**. Quick start:

```bash
./scripts/local_supabase.sh start
python scripts/verify_schema.py
uvicorn app.main:app --reload --port 8000
```

Uses `backend/.env.local` to override cloud `SUPABASE_URL` without editing `.env`.

## AI evaluation (writing + speaking) — offline by default

See **[docs/ai-eval-local.md](docs/ai-eval-local.md)**.

```bash
# Recommended local flags (already in .env.example / .env.local)
WRITING_EVAL_STUB=true
SPEAKING_EVAL_STUB=true
WRITING_LLM_PRIMARY=none
WRITING_LLM_FALLBACK=none
CLAUDE_DAILY_LIMIT=20
CLAUDE_MONTHLY_LIMIT=100

python scripts/writing_eval_smoke.py
python scripts/evaluate_fixture.py --all
python scripts/speaking_eval_smoke.py
```

Live Claude: set `WRITING_EVAL_STUB=false` and `WRITING_LLM_PRIMARY=claude`, then run `python scripts/evaluate_fixture.py <fixture> --live`.

Admin AI ops dashboard: `/admin/ai` (budget, cost estimate, latency, circuit, failures).
Admin Python package source: `../admin/api/` (symlinked as `app/admin`). Admin UI: `../admin/web`.

## Phase 2 — fewer DB round-trips

See **[docs/PHASE2.md](docs/PHASE2.md)**. Migrations:

- `20260601120000_mock_start_context_rpc.sql` — start mock (fewer reads)
- `20260601140000_module_submit_bundle_rpc.sql` — submit (one write transaction)

Included in `supabase db reset` / applied on cloud via dashboard or MCP.

## Database migration

Phase 1 tables **`users`** and **`mock_tests`** already exist — do not recreate.

1. Open [Supabase SQL Editor](https://supabase.com/dashboard) for your project.
2. Paste and run:

   `supabase/migrations/20260518120000_phase2_new_tables.sql`

3. Verify:

   ```bash
   python scripts/verify_schema.py
   python scripts/verify_r2.py
   ```

### Schema note

Your handoff copy of **Section 2.2** was truncated at `ANSWERS.id`. The migration includes `answers`, `module_scores`, and `speaking_reviews` with columns aligned to tasks A2/A3/C4 and the Day 1 roadmap — **confirm the remainder of Section 2.2 with the founder** and adjust the migration if the manual differs.

Fully specified in your paste:

- `questions` — all columns match Section 2.2
- `test_attempts` — all columns match Section 2.2

## Auth (`/auth/*`)

JWT access + refresh (httpOnly cookies). Implemented in `app/auth/`.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | Email signup — sends verification email, **no cookies** |
| POST | `/auth/login` | Email login — requires `email_verified_at` |
| POST | `/auth/send-otp` | Phone OTP (MSG91) — **503** unless `PHONE_OTP_ENABLED=true` |
| POST | `/auth/verify-otp` | Verify phone OTP — issues JWT cookies when enabled |
| POST | `/auth/send-email-otp` | Email OTP (Resend) — **503** unless `EMAIL_OTP_ENABLED=true` |
| POST | `/auth/verify-email-otp` | Verify email OTP — issues JWT cookies when enabled |
| POST | `/auth/verify-email` | Verify email — issues JWT cookies |
| POST | `/auth/refresh` | Rotate tokens |
| POST | `/auth/logout` | Revoke session |
| POST | `/auth/forgot-password` | Send reset email (Resend) |
| POST | `/auth/reset-password` | Set new password |
| GET | `/auth/me` | Current user (Bearer or `bf_access` cookie) |
| GET | `/auth/google/authorize` | Google OAuth URL (`?next=/dashboard`) |
| POST | `/auth/google/callback` | Exchange code → JWT cookies |

**Migration:** run `supabase/migrations/20260519120000_auth_tables.sql` in the Supabase SQL Editor (extends `users`, adds `otp_verifications`, `refresh_sessions`, `password_reset_tokens`).

**Env:** `JWT_SECRET`, `RESEND_API_KEY`, `FRONTEND_URL`, `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI`, `AUTH_SKIP_EMAIL_VERIFY` for local dev without Resend.

**Phone OTP (MSG91, India +91):** 4-digit codes. Set `PHONE_OTP_ENABLED=true`, `MSG91_AUTH_KEY`, `MSG91_TEMPLATE_ID` (Flow template variable must be named `otp`). Frontend: `NEXT_PUBLIC_PHONE_OTP_ENABLED=true`. Production must keep `AUTH_DEMO_OTP_ENABLED=false`, `AUTH_OPEN_OTP=false`, and empty `AUTH_DEMO_OTP`. Local/staging may use `AUTH_DEMO_OTP=1234` with `AUTH_DEMO_OTP_ENABLED=true`.

**Email OTP (Resend):** 6-digit codes. Set `EMAIL_OTP_ENABLED=true`, `RESEND_API_KEY`, verified `EMAIL_FROM` (not `onboarding@resend.dev` in prod). Frontend: `NEXT_PUBLIC_EMAIL_OTP_ENABLED=true`. Local/staging may use `AUTH_DEMO_OTP=123456` with `AUTH_DEMO_OTP_ENABLED=true`. See `backend/docs/EMAIL_OTP_RESEND.md`.

**Google:** In [Google Cloud Console](https://console.cloud.google.com/) create OAuth credentials (Web). Authorized redirect URI: `http://localhost:3000/api/auth/google/callback`. Run migration `20260520120000_users_google_id.sql`.

## Day 2 — Test engine (A1 + A2)

**Migration:** `supabase/migrations/20260522120000_test_attempts_module.sql` (adds `test_attempts.module`).

**Seed (dev):** `seed/day2_dev_seed.sql` then set Postman `mock_test_id` = `a0000000-0000-4000-8000-000000000001`.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/tests/{mock_test_id}/questions?module=reading\|listening` | Bearer | Questions only — **never** `correct_answer` |
| POST | `/api/tests/{mock_test_id}/start` | Bearer | Body `{ "module": "reading" }` → `attempt_id` |
| POST | `/api/attempts/{attempt_id}/submit` | Bearer | Body `{ "answers": [{ "question_id", "user_answer" }] }` |

Listening `audio_url` in DB = R2 object key; API returns presigned URLs in `audio_urls`.

Postman folder: **Day 2 — Sessions & questions**.

## Run API

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- App health: `GET http://localhost:8000/health`
- Tests router: `GET http://localhost:8000/api/tests/health`
- Auth: `GET http://localhost:8000/docs` → **auth** tag
- OpenAPI: `http://localhost:8000/docs`

## R2 signed URL (manual test)

```bash
python scripts/verify_r2.py
```

Or after starting the API: `GET http://127.0.0.1:8000/api/tests/r2-check`

```python
from app.storage.r2 import generate_signed_url
print(generate_signed_url("demo/user-1/part-1.webm"))
```

## Founder listening ingestion (S2 + S3)

Map founder JSON → DB rows + SQL seed. **Answers and transcripts are server-only**; audio is private R2 with presigned URLs after `POST /api/listening/{id}/start`.

- Spec: [`docs/listening_ingestion_mapping.md`](docs/listening_ingestion_mapping.md)
- Normalizer: `python -m scripts.normalize_listening_mock`
- **S2** — mock `e0000000-0000-4000-8000-000000000002`, audio `test/MT1/LT/audio/Listening_S2_Audio.mp3` → `--preset bandforge-s2`
- **S3** — mock `e0000000-0000-4000-8000-000000000003`, audio `test/MT1/LT/audio/Listening_S3_Audio.mp3` → `--preset bandforge-s3`
- **S4** — mock `e0000000-0000-4000-8000-000000000004`, audio `test/MT1/LT/audio/Listening_S4_Audio.mp3` → `--preset bandforge-s4` (RTF: `test/MT1/LT/transcripts/Listening_S4_Elevenlabs_Transcript.rtf`)
- **M01** — full mock; upload: `python -m scripts.upload_m01_listening_audio`
- Verify: `python -m scripts.verify_listening_mock --mock-id <uuid>`
- R2 bucket must have **no public access**; do not commit MP3s (`test/MT1/LT/audio/*.mp3`, `test/MT2/LT/audio/*.mp3`, `audio_seed/**/full.mp3` are gitignored)

Frontend: `/test/listening?part=2` (Leisure Centre), `?part=3` (Tutorial), `?part=4` (Transit lecture)

## Postman-first testing (no frontend)

Use Postman only until APIs are stable, then wire the Next.js app later.

### 1. Start the API

```bash
cd backend
source .venv/bin/activate
# Free port 8000 if needed: lsof -ti :8000 | xargs kill
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Import collection + environment

In Postman:

1. **Import** → `postman/BandForge-API.postman_collection.json`
2. **Import** → `postman/BandForge-Local.postman_environment.json`
3. Top-right env dropdown → **BandForge — Local**

### 3. Run requests (in order)

| Request | Expect |
|---------|--------|
| `GET /health` | `200` — `{"status":"ok"}` |
| `GET /api/tests/health` | `200` — tests router up |
| `GET /api/tests/db-check` | `200` if Supabase + migration OK; `503` with table details if not |
| `GET /api/tests/r2-check` | `200` if R2 upload + presigned URL OK; `503` if not |
| `GET /api/tests/r2-check` | `200` if R2 upload + presigned URL OK; `503` if not |

Optional: **Import** → **Link** → `http://localhost:8000/openapi.json` to pull new endpoints automatically as you add them.

### 4. Auth (when routes need it)

Protected routes will use `Authorization: Bearer <token>`. Set Postman env var `access_token` after Supabase phone OTP (Phase 1). Day 1 health / db-check / r2-check routes need **no auth**.

### 5. Variables for later flows

| Variable | Use |
|----------|-----|
| `base_url` | `http://localhost:8000` |
| `mock_test_id` | From admin / seed data |
| `attempt_id` | After `POST` start attempt |
| `user_id` | Test user uuid |
| `access_token` | Supabase JWT |
