"""HTTP timing middleware — logs duration for all app routes.

Emits one JSON line to stdout per request and sets ``X-Response-Time-Ms``.
Skips noisy Next/browser asset paths if proxied; covers ``/api``, ``/auth``,
``/admin``, ``/health``, and ``/``.
"""

from __future__ import annotations

import json
from time import perf_counter

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.cache.hybrid_cache import reset_cache_hit, was_cache_hit

# Skip OpenAPI UI assets and favicon noise.
_SKIP_PREFIXES = (
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon",
)


class ApiTimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if any(path == p or path.startswith(p + "/") for p in _SKIP_PREFIXES):
            return await call_next(request)

        reset_cache_hit()
        started = perf_counter()
        response = await call_next(request)
        duration_ms = round((perf_counter() - started) * 1000, 2)

        if was_cache_hit():
            response.headers["X-Cache-Hit"] = "1"
        cache_hit = response.headers.get("X-Cache-Hit") == "1"
        response.headers["X-Response-Time-Ms"] = str(duration_ms)

        try:
            from app.reliability.metrics import record_latency

            record_latency(path, duration_ms)
        except Exception:
            pass

        print(
            json.dumps(
                {
                    "route": path,
                    "method": request.method,
                    "duration_ms": duration_ms,
                    "cache_hit": cache_hit,
                    "cache_layer": "service" if cache_hit else "none",
                    "status": response.status_code,
                }
            )
        )
        return response
