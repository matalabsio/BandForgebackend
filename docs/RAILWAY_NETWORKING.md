# Railway networking — fix public 502

If deploy logs show gunicorn listening (e.g. `0.0.0.0:8080`) and internal `/health` returns 200, but the public URL returns:

```json
{"status":"error","code":502,"message":"Application failed to respond"}
```

with header `x-railway-fallback: true`, the edge proxy is routing to the **wrong port**.

## Fix (2 minutes)

1. Railway → **adequate-surprise** (API service) → **Settings** → **Networking**
2. Open the public domain (e.g. `adequate-surprise-production-0f84.up.railway.app`)
3. **Target Port** — pick ONE of these (both work after dual-bind deploy):
   - **Recommended:** clear Target Port (Railway routes to injected `$PORT`, e.g. `8080`)
   - **Or** leave Target Port at `8000` (entrypoint binds `$PORT` + `8000`)
4. Confirm deploy logs include: `Railway dual-bind: 0.0.0.0:8080 + 0.0.0.0:8000`
5. Ensure **Public Networking** is enabled (service must not stay "Unexposed")
6. Redeploy from latest `main` (must include dual-bind entrypoint), then:

```bash
curl -fsS https://YOUR-SERVICE.up.railway.app/health
# {"status":"ok"}
```

## Required production variables

```env
APP_ENV=production
API_HOST=0.0.0.0
FRONTEND_URL=https://bandforge-web.vercel.app
GOOGLE_REDIRECT_URI=https://bandforge-web.vercel.app/api/auth/google/callback
CORS_ORIGINS=https://bandforge-web.vercel.app
```

See also: `BandForge Brand/docs/railway.md` in the monorepo.
