from functools import lru_cache
import time
from typing import Callable, TypeVar

import httpx
from supabase import Client, create_client

from app.config import get_settings

T = TypeVar("T")


def _is_transient_supabase_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    transient_markers = (
        "http2",
        "keyerror",
        "stream",
        "connection",
        "disconnect",
        "timeout",
        "temporarily unavailable",
        "remoteprotocolerror",
        "proxyerror",
        "server disconnected",
    )
    return any(marker in msg for marker in transient_markers)


@lru_cache
def get_supabase() -> Client:
    settings = get_settings()
    client = create_client(
        settings.supabase_url_normalized,
        settings.supabase_secret_key,
    )
    # Force HTTP/1.1 — Supabase HTTP/2 streams can drop under burst traffic.
    try:
        postgrest = client.postgrest
        if hasattr(postgrest, "session"):
            old = postgrest.session
            postgrest.session = httpx.Client(
                http2=False,
                headers=dict(old.headers),
                timeout=old.timeout,
            )
    except Exception:
        pass
    return client


def execute_with_retry(fn: Callable[[], T], *, retries: int = 2, base_delay_s: float = 0.15) -> T:
    """Retry transient Supabase transport failures with small backoff."""
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if not _is_transient_supabase_error(exc) or attempt >= retries:
                raise
            time.sleep(base_delay_s * (attempt + 1))
    assert last is not None
    raise last
