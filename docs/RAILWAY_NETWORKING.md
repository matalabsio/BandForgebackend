# Railway 502 — Application failed to respond

Public URL returns:

```json
{"status":"error","code":502,"message":"Application failed to respond"}
```

Header: `x-railway-fallback: true`

## Quick fix (do all steps)

### 1. Redeploy latest `main`

Railway → **adequate-surprise** → **Deployments** → **Redeploy** (or push to `main`).

Deploy logs **must** show:

```text
[bandforge-api] railway=true ... bind=8080 8000
```

(or similar with your `$PORT` plus 8000/8080)

### 2. Fix Networking (most important)

**Settings → Networking →** click `adequate-surprise-production-96bc.up.railway.app`

| Option A (recommended) | Option B |
|------------------------|----------|
| **Delete** the public domain | Set **Target Port** to `8080` |
| Click **Generate Domain** again | (match deploy log `Listening at ...:8080`) |
| When asked for port, use **`8080`** | |

Also ensure **Public Networking** is **ON** (not Unexposed).

### 3. Set Railway variables

```env
APP_ENV=production
API_HOST=0.0.0.0
FRONTEND_URL=https://bandforge-web.vercel.app
GOOGLE_REDIRECT_URI=https://bandforge-web.vercel.app/api/auth/google/callback
CORS_ORIGINS=https://bandforge-web.vercel.app
```

#### Razorpay Test checkout (pricing page)

If `/pricing` shows “Checkout unavailable”, the API is returning `payments_enabled: false`.
Set on **Railway → adequate-surprise → Variables** (not only `backend/.env` locally):

```env
RAZORPAY_ENABLED=true
RAZORPAY_KEY_ID=rzp_test_...          # Test mode keys from Razorpay Dashboard
RAZORPAY_KEY_SECRET=...
# Optional for Test on prod (/verify still works); required for rzp_live_*:
RAZORPAY_WEBHOOK_SECRET=...
```

Redeploy, then verify:

```bash
curl -sS https://adequate-surprise-production-96bc.up.railway.app/api/payments/plans | jq '.payments_enabled'
# true
```

Deploy logs should include `Razorpay credentials OK (API probe passed)`.

Optional if port mismatch persists:

```env
PORT=8000
```

Then set domain **Target Port** to `8000` to match.

### 4. Verify

```bash
curl -fsS https://adequate-surprise-production-96bc.up.railway.app/health
# {"status":"ok"}

curl -fsS https://bandforge-web.vercel.app/api/health
# {"frontend":"ok","backend":"ok",...}
```

## Why this happens

Railway injects `PORT=8080` for healthchecks, but the public domain may route to port **8000**. The entrypoint binds **8080 + 8000 + $PORT** so both paths work — but only after a successful redeploy from current `main`.

## Still broken?

Paste deploy logs from container start through first `/health` request.
