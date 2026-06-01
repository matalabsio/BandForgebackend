"""HTTP timing middleware for /api/* routes."""

from __future__ import annotations

import json
from time import perf_counter

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from app.cache.hybrid_cache import reset_cache_hit, was_cache_hit


class ApiTimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        reset_cache_hit()
        started = perf_counter()
        response = await call_next(request)
        if was_cache_hit():
            response.headers["X-Cache-Hit"] = "1"
        cache_hit = response.headers.get("X-Cache-Hit") == "1"
        print(
            json.dumps(
                {
                    "route": path,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                    "cache_hit": cache_hit,
                    "cache_layer": "service" if cache_hit else "none",
                    "status": response.status_code,
                }
            )
        )
        return response
