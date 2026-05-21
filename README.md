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

## Setup

```bash
cd backend
python3.11 -m venv .venv   # requires Python 3.10+
source .venv/bin/activate
pip install -r requirements.txt
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
| POST | `/auth/send-otp` | Phone OTP — **503** unless `PHONE_OTP_ENABLED=true` |
| POST | `/auth/verify-otp` | Verify phone OTP — **503** unless enabled |
| POST | `/auth/verify-email` | Verify email — issues JWT cookies |
| POST | `/auth/refresh` | Rotate tokens |
| POST | `/auth/logout` | Revoke session |
| POST | `/auth/forgot-password` | Send reset email (Resend) |
| POST | `/auth/reset-password` | Set new password |
| GET | `/auth/me` | Current user (Bearer or `bf_access` cookie) |
| GET | `/auth/google/authorize` | Google OAuth URL (`?next=/dashboard`) |
| POST | `/auth/google/callback` | Exchange code → JWT cookies |

**Migration:** run `supabase/migrations/20260519120000_auth_tables.sql` in the Supabase SQL Editor (extends `users`, adds `otp_verifications`, `refresh_sessions`, `password_reset_tokens`).

**Env:** see `.env.example` — `JWT_SECRET`, `RESEND_API_KEY`, `FRONTEND_URL`, `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI`, `PHONE_OTP_ENABLED=false`, `AUTH_SKIP_EMAIL_VERIFY` for local dev without Resend.

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
