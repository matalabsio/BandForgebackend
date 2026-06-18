from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.config import get_settings, reload_settings, settings_diagnostics
from app.cache.hybrid_cache import redis_status
from app.middleware.timing import ApiTimingMiddleware
from app.admin import router as admin_router
from app.auth import router as auth_router
from app.listening import router as listening_router
from app.reading import router as reading_router
from app.writing import router as writing_router
from app.routers import attempts, dashboard, mock_attempts, tests


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = reload_settings()
    diag = settings_diagnostics()
    google_ok = bool(
        settings.google_client_id
        and settings.google_client_secret
        and settings.google_redirect_uri
    )
    print(
        f"[bandforge-api] Supabase project_ref={diag['project_ref']} "
        f"url={diag['supabase_url']} "
        f"env_local_active={diag['env_local_active']} "
        f"google_oauth={'on' if google_ok else 'off'} "
        f"redis={redis_status()}"
    )
    yield


app = FastAPI(
    title="BandForge API",
    description="bandforge-api — test engine, evaluation, async jobs",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(ApiTimingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(tests.router)
app.include_router(attempts.router)
app.include_router(dashboard.router)
app.include_router(mock_attempts.router)
app.include_router(listening_router)
app.include_router(reading_router)
app.include_router(writing_router)


@app.get("/", response_class=HTMLResponse, include_in_schema=True)
def root() -> str:
    """Browser-friendly landing page when visiting the API base URL."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BandForge API</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 40rem; margin: 3rem auto; padding: 0 1rem; color: #1c1917; }
    h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
    .ok { color: #047857; font-weight: 600; }
    ul { line-height: 1.8; }
    a { color: #0d9488; }
    code { background: #f5f5f4; padding: 0.1em 0.35em; border-radius: 4px; font-size: 0.9em; }
  </style>
</head>
<body>
  <h1>BandForge API</h1>
  <p class="ok">Python backend is running.</p>
  <p>FastAPI · bandforge-api (local)</p>
  <ul>
    <li><a href="/docs">Swagger UI</a> — <code>/docs</code></li>
    <li><a href="/health">Health</a> — <code>/health</code></li>
    <li><a href="/api/tests/health">Tests router</a> — <code>/api/tests/health</code></li>
    <li><a href="/api/tests/db-check">DB check</a> — <code>/api/tests/db-check</code></li>
    <li><a href="/api/tests/r2-check">R2 check</a> — <code>/api/tests/r2-check</code></li>
  </ul>
</body>
</html>"""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
