# BandForge API — EC2 deployment (Ubuntu, from scratch)

Complete guide to run **bandforge-api** on **AWS EC2 (Ubuntu)** with Docker, HTTPS, and **Vercel** for the frontend.

**Auth flows (Google, cookies, env vars, troubleshooting):** **[opy.md](../../opy.md)** at repo root.

**Assumption:** You already launched an EC2 instance. This doc covers everything after that.

---

## 1. Architecture

```text
Users
  │
  ▼
Vercel (frontend repo)          https://app.yourdomain.com
  │  BFF: /api/auth/*, /api/listening/*, …
  │  NEXT_PUBLIC_API_URL → https://api.yourdomain.com
  ▼
EC2 Ubuntu + Docker             https://api.yourdomain.com
  │  nginx (TLS) → 127.0.0.1:8000 → bandforge-api container
  ▼
Supabase (hosted Postgres)      same AWS region as EC2
Upstash Redis (optional)        same region as EC2
Cloudflare R2                   listening audio
Resend                          email verify / reset
Google OAuth                    login
```

| Component | Where | Never put on |
|-----------|--------|----------------|
| Next.js UI | Vercel | EC2 |
| FastAPI API | EC2 (Docker) | Vercel |
| Database | Supabase cloud | EC2 disk |
| `backend/.env.local` | Local dev only | EC2 |

---

## 2. Before you SSH — checklist

### 2.1 EC2 instance

| Setting | Recommendation |
|---------|----------------|
| OS | **Ubuntu 22.04 or 24.04 LTS** |
| Type | **t3.small** minimum (2 vCPU, 2 GB RAM); **t3.medium** for production traffic |
| Region | Same as **Supabase** project (e.g. `ap-south-1` for India) |
| Storage | 20–30 GB gp3 |
| Key pair | Download `.pem` once; `chmod 400` on your Mac |

### 2.2 Security group (inbound)

| Type | Port | Source | Purpose |
|------|------|--------|---------|
| SSH | 22 | **Your IP only** (not `0.0.0.0/0`) | Admin |
| HTTP | 80 | `0.0.0.0/0` | Let’s Encrypt + redirect to HTTPS |
| HTTPS | 443 | `0.0.0.0/0` | Public API |
| Custom TCP | 8000 | **Do not open** publicly | API stays on localhost behind nginx |

### 2.3 DNS (Route 53 or any registrar)

Create an **A record** pointing to your EC2 **public IP** (or Elastic IP):

```text
api.yourdomain.com  →  <EC2_PUBLIC_IP>
```

Optional: `app.yourdomain.com` → Vercel (CNAME to Vercel).

### 2.4 Supabase (production project)

1. Create a **production** Supabase project (separate from local dev).
2. Apply all migrations under `backend/supabase/migrations/` (27 files), in filename order:
   - Supabase Dashboard → **SQL Editor**, or
   - `supabase link` + `supabase db push` from your laptop.
3. Confirm RPCs exist (SQL):

```sql
SELECT proname FROM pg_proc
WHERE proname IN (
  'get_mock_attempt_progress',
  'get_mock_start_context',
  'persist_module_submit_bundle'
);
```

4. Copy from Dashboard → **Settings → API**:
   - Project URL → `SUPABASE_URL`
   - **service_role / secret** key → `SUPABASE_SECRET_KEY` (never expose to browser or Vercel)

### 2.5 Other services

| Service | What you need |
|---------|----------------|
| **Upstash Redis** | `REDIS_URL` (`rediss://…`) in same region as EC2 |
| **Cloudflare R2** | Account ID, access key, secret, bucket, endpoint |
| **Resend** | API key + verified domain for `EMAIL_FROM` |
| **Google Cloud Console** | OAuth client; redirect URI = `https://app.yourdomain.com/api/auth/google/callback` |

Generate strong secrets locally (do not commit):

```bash
openssl rand -hex 32   # use for JWT_SECRET
openssl rand -hex 32   # use for JWT_REFRESH_SECRET
```

---

## 3. Connect to EC2

Replace values with yours:

```bash
chmod 400 ~/Downloads/your-key.pem
ssh -i ~/Downloads/your-key.pem ubuntu@<EC2_PUBLIC_IP>
```

Optional: attach an **Elastic IP** in AWS console so the IP does not change on stop/start.

---

## 4. Server setup (Ubuntu)

Run on the instance as `ubuntu`:

```bash
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y git curl ca-certificates gnupg
```

### 4.1 Install Docker (official)

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker ubuntu
```

Log out and SSH back in so `docker` works without `sudo`:

```bash
exit
# ssh again…
docker --version
docker compose version
```

### 4.2 Firewall (UFW)

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

---

## 5. Deploy application code

### Option A — Git clone (recommended)

If the backend lives in a repo (or monorepo):

```bash
mkdir -p ~/apps && cd ~/apps
git clone https://github.com/YOUR_ORG/YOUR_BACKEND_REPO.git bandforge-api
cd bandforge-api
```

**Monorepo:** clone the full repo, then work in `backend/`:

```bash
git clone https://github.com/YOUR_ORG/MATA-lab.git
cd MATA-lab/backend
```

### Option B — Copy from laptop (no Git on server)

On your Mac:

```bash
cd /path/to/MATA-lab
rsync -avz --exclude '.venv' --exclude '__pycache__' --exclude '.env' \
  -e "ssh -i ~/Downloads/your-key.pem" \
  backend/ ubuntu@<EC2_PUBLIC_IP>:~/apps/bandforge-api/
```

On EC2:

```bash
cd ~/apps/bandforge-api
```

---

## 6. Configure environment

On EC2, in the **`backend`** directory (where `Dockerfile` and `docker-compose.yml` live):

```bash
cp .env.docker.example .env
nano .env
```

Fill every value. Minimum for a working deploy:

```env
APP_ENV=production
API_PUBLISH_PORT=8000
WEB_CONCURRENCY=2

SUPABASE_URL=https://xxxxxxxx.supabase.co
SUPABASE_SECRET_KEY=sb_secret_...

JWT_SECRET=<64-char hex from openssl>
JWT_REFRESH_SECRET=<64-char hex from openssl>

FRONTEND_URL=https://app.yourdomain.com
CORS_ORIGINS=

REDIS_URL=rediss://default:xxxx@xxxx.upstash.io:6379

GOOGLE_CLIENT_ID=....apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://app.yourdomain.com/api/auth/google/callback

RESEND_API_KEY=re_...
EMAIL_FROM=BandForge <noreply@yourdomain.com>
AUTH_SKIP_EMAIL_VERIFY=false
PHONE_OTP_ENABLED=false

R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET_NAME=bandforge-speaking-audio
R2_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com
```

**Rules:**

- Do **not** copy `backend/.env.local` to EC2.
- Do **not** commit `.env` to Git.
- `chmod 600 .env`

---

## 7. Build and run API (Docker Compose)

```bash
cd ~/apps/bandforge-api   # or ~/apps/MATA-lab/backend
docker compose up -d --build
```

Verify on the server:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/api/tests/health
docker compose ps
docker compose logs --tail=50 api
```

Expected log line (similar):

```text
[bandforge-api] ... env_local_active=False google_oauth=on redis=ok
```

If the container exits:

```bash
docker compose logs api
```

Common fixes: missing `SUPABASE_URL` / `SUPABASE_SECRET_KEY`, invalid `REDIS_URL`.

---

## 8. HTTPS with nginx + Let’s Encrypt

Install nginx and Certbot:

```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx
```

Create site config (replace domain):

```bash
sudo nano /etc/nginx/sites-available/bandforge-api
```

Paste:

```nginx
server {
    listen 80;
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 120s;
        proxy_send_timeout 120s;
    }
}
```

Enable and test:

```bash
sudo ln -sf /etc/nginx/sites-available/bandforge-api /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d api.yourdomain.com
```

Certbot will add HTTPS and redirect HTTP → HTTPS.

Test from your laptop:

```bash
curl -fsS https://api.yourdomain.com/health
```

Open in browser: `https://api.yourdomain.com/docs` (Swagger).

---

## 9. Deploy frontend on Vercel

1. Import **frontend** repo (or monorepo with **Root Directory** = `frontend`).
2. **Environment variables** (Production):

| Variable | Value |
|----------|--------|
| `NEXT_PUBLIC_API_URL` | `https://api.yourdomain.com` |
| `NEXT_PUBLIC_AUTH_ENABLED` | `true` |
| `NEXT_PUBLIC_PHONE_OTP_ENABLED` | `false` |

3. Deploy. Custom domain: `app.yourdomain.com`.

4. **Google OAuth** — Authorized redirect URI (exact):

```text
https://app.yourdomain.com/api/auth/google/callback
```

Must match `GOOGLE_REDIRECT_URI` in EC2 `backend/.env`.

5. Update EC2 `.env` if needed:

```env
FRONTEND_URL=https://app.yourdomain.com
```

Then:

```bash
docker compose up -d
```

---

## 10. End-to-end smoke test

1. `curl https://api.yourdomain.com/health` → `{"status":"ok"}`
2. Open `https://app.yourdomain.com`
3. Sign up / log in (email or Google)
4. Dashboard loads (no “Backend API is not reachable”)
5. Start **Test 1** listening → submit → reading → writing
6. Check EC2 logs during test:

```bash
docker compose logs -f --tail=100 api
```

---

## 11. Updates (new code release)

On EC2:

```bash
cd ~/apps/bandforge-api   # or .../MATA-lab/backend
git pull
docker compose build
docker compose up -d
docker compose ps
curl -fsS http://127.0.0.1:8000/health
```

If you only changed `.env`:

```bash
docker compose up -d
```

New Supabase migrations: apply on **Supabase prod** first, then redeploy API.

---

## 12. Optional hardening

| Task | Command / note |
|------|----------------|
| Auto security updates | `sudo apt-get install -y unattended-upgrades` |
| Fail2ban | `sudo apt-get install -y fail2ban` |
| Log rotation | Docker compose already limits log size |
| Backups | Supabase dashboard backups; not EC2 |
| Monitoring | AWS CloudWatch agent or Uptime on `/health` |
| Restrict SSH | Security group: your IP only |

---

## 13. Troubleshooting

### Symptom: Google login → `Internal Server Error`, dashboard `HTTP 401`, `restore`/`refresh` **500**

**Cause:** EC2 `backend/.env` still points at **local** Supabase (`http://127.0.0.1:54321`). Inside Docker on EC2, that address is the container itself — not your database. Google callback cannot create/read users → 500. No valid cookies → dashboard 401.

**Verify from your laptop:**

```bash
curl -sS http://<EC2_IP>:8000/api/tests/db-check | jq .
```

Bad: `"supabase_url":"http://127.0.0.1:54321"`, `"supabase_host":"auth_error"`.

**Fix on EC2** (SSH in):

```bash
cd ~/bandforge-api   # or your deploy path
nano .env
```

Set (copy **cloud** values from your laptop `backend/.env`, not `.env.local`):

```env
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_SECRET_KEY=sb_secret_...   # Dashboard → Settings → API → secret / service_role
APP_ENV=production

# Local frontend testing against EC2 API:
FRONTEND_URL=http://localhost:3000
GOOGLE_REDIRECT_URI=http://localhost:3000/api/auth/google/callback
```

Also copy `JWT_SECRET` and `JWT_REFRESH_SECRET` from laptop `.env` **or** keep EC2 values and clear browser cookies after fix (old tokens won’t match).

```bash
docker compose up -d
curl -sS http://127.0.0.1:8000/api/tests/db-check
```

Good: `"api":"ok"` without `auth_error`.

**Local frontend** (`frontend/.env`):

```env
NEXT_PUBLIC_API_URL=http://<EC2_PUBLIC_IP>:8000
```

Restart: `npm run dev`. Clear site cookies for `localhost:3000`.

**Google Cloud Console** (same OAuth client as EC2 `GOOGLE_CLIENT_ID`):

| Field | Value (local dev + EC2 API) |
|-------|-----------------------------|
| Authorized JavaScript origins | `http://localhost:3000` |
| Authorized redirect URIs | `http://localhost:3000/api/auth/google/callback` |

When you deploy frontend to Vercel, **add** (do not remove localhost if you still test locally):

- Origin: `https://app.yourdomain.com`
- Redirect: `https://app.yourdomain.com/api/auth/google/callback`

Update EC2 `.env` `FRONTEND_URL` and `GOOGLE_REDIRECT_URI` to match production.

---

| Symptom | Cause | Fix |
|---------|--------|-----|
| `ECONNREFUSED` on frontend | API down or wrong `NEXT_PUBLIC_API_URL` | `docker compose ps`; fix Vercel env; redeploy Vercel |
| `502 Bad Gateway` (nginx) | Container not running | `docker compose logs api`; `docker compose up -d` |
| Auth 500 / DB errors | Wrong Supabase keys or migrations missing | Verify `.env`; run migrations on prod project |
| `redis=error` in logs | Bad `REDIS_URL` or Upstash blocked | Fix URL; allow EC2 egress to Upstash |
| Very slow mocks (~10s) | Supabase far from EC2 | Move EC2 or Supabase to same region |
| Google login `fetch failed` | Redirect URI mismatch | Google Console + `GOOGLE_REDIRECT_URI` + Vercel domain |
| CORS errors (rare) | Direct browser → API | Set `FRONTEND_URL`; add preview URL to `CORS_ORIGINS` |
| Port 8000 conflict | uvicorn + Docker both on 8000 | Stop uvicorn on host; only use Docker on EC2 |
| Certbot fails | DNS not pointing to EC2 | Fix A record; wait for propagation |

**Useful commands:**

```bash
docker compose ps
docker compose logs -f api
docker compose restart api
sudo systemctl status nginx
sudo nginx -t
curl -v http://127.0.0.1:8000/health
curl -v https://api.yourdomain.com/health
```

---

## 14. Local Docker vs EC2 (reference)

| | Local Mac | EC2 production |
|--|-----------|----------------|
| Start | `cd backend && docker compose up -d` | Same |
| URL | `http://127.0.0.1:8000` | `https://api.yourdomain.com` |
| Frontend | `npm run dev` + `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` | Vercel + HTTPS API URL |
| Supabase | Cloud `.env` or local `supabase start` | **Cloud prod only** |
| TLS | Not required | nginx + Certbot |

---

## 15. File reference (this repo)

| Path | Role |
|------|------|
| `backend/Dockerfile` | Production image |
| `backend/docker-compose.yml` | EC2 service definition |
| `backend/.env.docker.example` | Env template |
| `backend/docs/DOCKER.md` | Docker quick reference |
| `backend/supabase/migrations/` | Database schema (apply on Supabase) |
| `frontend/` | Deploy to Vercel only |

---

## Quick command summary (copy-paste)

```bash
# On EC2 (after SSH)
sudo apt-get update && sudo apt-get upgrade -y
# … install Docker (section 4.1) …
cd ~/apps/MATA-lab/backend
cp .env.docker.example .env && nano .env
docker compose up -d --build
curl -fsS http://127.0.0.1:8000/health
# … nginx + certbot (section 8) …
curl -fsS https://api.yourdomain.com/health
```

Then set Vercel `NEXT_PUBLIC_API_URL=https://api.yourdomain.com` and ship the frontend.
