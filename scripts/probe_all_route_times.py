#!/usr/bin/env python3
"""Probe response times across frontend, backend, and admin.

Measures wall-clock client time for each request. When the backend sets
``X-Response-Time-Ms``, that server duration is recorded too.

Usage:
  # Public + guest probes (no login)
  .venv/bin/python scripts/probe_all_route_times.py

  # Google-auth users (no password) — mints a local session by email
  TEST_EMAIL=you@gmail.com .venv/bin/python scripts/probe_all_route_times.py --warm \\
    --out docs/route-timing-probe.json

  # Password login (email/password accounts only)
  TEST_EMAIL=... TEST_PASSWORD=... .venv/bin/python scripts/probe_all_route_times.py

  # Or paste an existing access JWT
  BF_ACCESS='eyJ...' .venv/bin/python scripts/probe_all_route_times.py

Writes JSON to stdout and optionally --out path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from http.cookiejar import Cookie, CookieJar
from typing import Any
from urllib.parse import urljoin

FRONTEND = os.environ.get("FRONTEND_URL", "http://localhost:3000").rstrip("/")
BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
ADMIN = os.environ.get("ADMIN_URL", "http://127.0.0.1:3001").rstrip("/")


@dataclass
class Sample:
    app: str
    kind: str  # page | api | bff
    method: str
    path: str
    status: int
    client_ms: float
    server_ms: float | None
    auth: str  # public | guest | user | admin | none
    note: str = ""


class Client:
    def __init__(self) -> None:
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        self.bearer: str | None = None

    def set_bearer(self, token: str) -> None:
        self.bearer = token.strip()

    def set_auth_cookies(self, *, access: str, refresh: str) -> None:
        """Inject bf_access / bf_refresh for browser-style BFF cookie auth."""
        for domain in ("127.0.0.1", "localhost"):
            for name, value in (("bf_access", access), ("bf_refresh", refresh)):
                self.jar.set_cookie(
                    Cookie(
                        version=0,
                        name=name,
                        value=value,
                        port=None,
                        port_specified=False,
                        domain=domain,
                        domain_specified=True,
                        domain_initial_dot=False,
                        path="/",
                        path_specified=True,
                        secure=False,
                        expires=None,
                        discard=True,
                        comment=None,
                        comment_url=None,
                        rest={},
                        rfc2109=False,
                    )
                )

    def request(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 45.0,
    ) -> tuple[int, float, float | None, bytes]:
        data = None
        hdrs = {"Accept": "application/json, text/html, */*"}
        if self.bearer:
            hdrs["Authorization"] = f"Bearer {self.bearer}"
        if headers:
            hdrs.update(headers)
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        t0 = time.perf_counter()
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                payload = resp.read()
                status = resp.status
                server_hdr = resp.headers.get("X-Response-Time-Ms")
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            status = exc.code
            server_hdr = exc.headers.get("X-Response-Time-Ms") if exc.headers else None
        except Exception as exc:  # noqa: BLE001
            client_ms = round((time.perf_counter() - t0) * 1000, 1)
            raise RuntimeError(f"{method} {url} failed: {exc}") from exc
        client_ms = round((time.perf_counter() - t0) * 1000, 1)
        server_ms = float(server_hdr) if server_hdr else None
        return status, client_ms, server_ms, payload


def probe(
    client: Client,
    *,
    app: str,
    kind: str,
    method: str,
    base: str,
    path: str,
    auth: str,
    body: dict[str, Any] | None = None,
    note: str = "",
) -> Sample:
    url = base + "/" if path == "/" else (base + path if path.startswith("/") else urljoin(base + "/", path))
    try:
        status, client_ms, server_ms, _ = client.request(method, url, body=body)
        return Sample(app, kind, method, path, status, client_ms, server_ms, auth, note)
    except RuntimeError as exc:
        return Sample(app, kind, method, path, 0, 0.0, None, auth, str(exc)[:120])


def login(client: Client, email: str, password: str) -> bool:
    status, _, _, _ = client.request(
        "POST",
        f"{BACKEND}/auth/login",
        body={"email": email, "password": password},
    )
    return status == 200


def mint_session_for_email(email: str) -> tuple[str, str, str] | None:
    """Issue access+refresh for a Google (or any) user by email — local probe only."""
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)

    from uuid import UUID

    from app.auth import service as auth_service
    from app.db.supabase_client import get_supabase

    email_l = email.strip().lower()
    # Ignore placeholder ellipsis from copy-pasted docs
    if not email_l or email_l in {"…", "...", "you@gmail.com"}:
        return None

    sb = get_supabase()
    rows = (
        sb.table("users")
        .select("id, email, phone, role, is_active, google_id")
        .eq("email", email_l)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        print(f"WARN: no user row for {email_l}", file=sys.stderr)
        return None
    row = rows[0]
    if not row.get("is_active", True):
        print(f"WARN: user {email_l} is inactive", file=sys.stderr)
        return None
    access, refresh, _sid = asyncio.run(
        auth_service.issue_session_tokens(
            user_id=UUID(str(row["id"])),
            email=row.get("email"),
            phone=row.get("phone"),
            user_agent="probe_all_route_times",
            ip_address="127.0.0.1",
        )
    )
    role = str(row.get("role") or "student")
    via = "google" if row.get("google_id") else "email"
    print(f"Minted session for {email_l} (role={role}, via={via})", file=sys.stderr)
    return access, refresh, role


def guest_session(client: Client) -> bool:
    status, _, _, _ = client.request(
        "POST", f"{BACKEND}/api/diagnostic/guest-session", body={}
    )
    return status in (200, 201)


def load_openapi_gets(client: Client) -> list[str]:
    status, _, _, payload = client.request("GET", f"{BACKEND}/openapi.json")
    if status != 200:
        return []
    data = json.loads(payload)
    out: list[str] = []
    for path, methods in (data.get("paths") or {}).items():
        if "get" not in methods:
            continue
        if "{" in path:
            continue
        out.append(path)
    return sorted(out)


FRONTEND_PAGES = [
    "/",
    "/about",
    "/features",
    "/pricing",
    "/faq",
    "/contact",
    "/how-it-works",
    "/drills",
    "/demo",
    "/why",
    "/stories",
    "/mobile",
    "/ai-feedback",
    "/speaking",
    "/writing",
    "/blog",
    "/hyderabad",
    "/vs-coaching-centres",
    "/urdu",
    "/telugu",
    "/terms",
    "/privacy-policy",
    "/refund-policy",
    "/login",
    "/signup",
    "/forgot-password",
    "/diagnostic",
    "/dashboard",
    "/study-plan",
    "/study-plan/today",
    "/scores",
    "/profile",
    "/profile/billing",
    "/plan",
    "/streak",
    "/content-library",
    "/test",
    "/practice/listening",
    "/practice/reading",
    "/practice/writing",
    "/practice/speaking",
]

FRONTEND_BFF = [
    ("GET", "/api/health"),
    ("GET", "/api/auth/session"),
    ("GET", "/api/auth/me"),
    ("GET", "/api/payments/plans"),
    ("GET", "/api/payments/subscription"),
    ("GET", "/api/dashboard/summary"),
    ("GET", "/api/learning/profile"),
    ("GET", "/api/practice/hubs?skill=listening"),
    ("GET", "/api/practice/progress"),
    ("GET", "/api/mock-attempts/catalog"),
    ("GET", "/api/mock-attempts/session"),
    ("GET", "/api/mock-attempts/in-progress"),
    ("GET", "/api/diagnostic/latest"),
    ("GET", "/api/tutor/suggestions"),
    ("GET", "/api/tests/health"),
    ("GET", "/api/tests/mock-tests"),
]

ADMIN_PAGES = [
    "/admin/login",
    "/admin",
    "/admin/users",
    "/admin/mocks",
    "/admin/question-bank",
    "/admin/question-bank/overview",
    "/admin/speaking",
    "/admin/writing",
    "/admin/diagnostics",
    "/admin/payments",
    "/admin/subscriptions",
    "/admin/review-analytics",
    "/admin/ai",
    "/admin/settings/audit",
]

ADMIN_BFF = [
    ("GET", "/api/admin/dashboard/overview"),
    ("GET", "/api/admin/dashboard/metrics"),
    ("GET", "/api/admin/users"),
    ("GET", "/api/admin/mocks"),
    ("GET", "/api/admin/question-bank"),
    ("GET", "/api/admin/speaking"),
    ("GET", "/api/admin/writing"),
    ("GET", "/api/admin/diagnostics"),
    ("GET", "/api/admin/payments"),
    ("GET", "/api/admin/subscriptions"),
    ("GET", "/api/admin/review-analytics"),
    ("GET", "/api/admin/ai/health"),
    ("GET", "/api/admin/ai/metrics"),
    ("GET", "/api/admin/audit"),
    ("GET", "/api/auth/session"),
]

BACKEND_PUBLIC_POSTS: list[tuple[str, dict[str, Any] | None]] = [
    ("/api/diagnostic/guest-session", {}),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="Write JSON results to this path")
    parser.add_argument("--warm", action="store_true", help="Warm pass before measuring")
    parser.add_argument("--samples", type=int, default=1, help="Samples per route (median)")
    args = parser.parse_args()

    email = os.environ.get("TEST_EMAIL", "").strip()
    password = os.environ.get("TEST_PASSWORD", "").strip()
    bf_access = os.environ.get("BF_ACCESS", "").strip()

    client = Client()
    samples: list[Sample] = []

    # --- Auth setup (Google users: TEST_EMAIL alone mints a session) ---
    auth_mode = "public"
    if bf_access:
        client.set_bearer(bf_access)
        auth_mode = "user"
        print("Using BF_ACCESS bearer token", file=sys.stderr)
    elif email and password and password not in {"…", "..."}:
        ok = login(client, email, password)
        auth_mode = "user" if ok else "public"
        if not ok:
            print(
                "WARN: password login failed; trying Google session mint…",
                file=sys.stderr,
            )
            minted = mint_session_for_email(email)
            if minted:
                access, refresh, role = minted
                client.set_bearer(access)
                client.set_auth_cookies(access=access, refresh=refresh)
                auth_mode = "admin" if role in {"admin", "super_admin"} else "user"
    elif email and email not in {"…", "..."}:
        minted = mint_session_for_email(email)
        if minted:
            access, refresh, role = minted
            client.set_bearer(access)
            client.set_auth_cookies(access=access, refresh=refresh)
            auth_mode = "admin" if role in {"admin", "super_admin"} else "user"
        else:
            print(
                "WARN: could not mint session; continuing with public/guest probes",
                file=sys.stderr,
            )

    guest_ok = guest_session(Client())
    if auth_mode == "public":
        if guest_session(client):
            auth_mode = "guest"

    def measure(
        app: str,
        kind: str,
        method: str,
        base: str,
        path: str,
        auth: str,
        body=None,
        note="",
    ) -> None:
        times: list[Sample] = []
        for _ in range(max(1, args.samples)):
            times.append(
                probe(
                    client,
                    app=app,
                    kind=kind,
                    method=method,
                    base=base,
                    path=path,
                    auth=auth,
                    body=body,
                    note=note,
                )
            )
        times.sort(key=lambda s: s.client_ms)
        samples.append(times[len(times) // 2])

    if args.warm:
        for p in ("/health", "/api/status/ping", "/api/payments/plans"):
            probe(
                client,
                app="backend",
                kind="api",
                method="GET",
                base=BACKEND,
                path=p,
                auth="public",
            )
        for p in ("/", "/login", "/pricing"):
            probe(
                client,
                app="frontend",
                kind="page",
                method="GET",
                base=FRONTEND,
                path=p,
                auth="public",
            )
        probe(
            client,
            app="admin",
            kind="page",
            method="GET",
            base=ADMIN,
            path="/admin/login",
            auth="public",
        )

    for path in load_openapi_gets(client):
        measure("backend", "api", "GET", BACKEND, path, auth_mode)

    for path, body in BACKEND_PUBLIC_POSTS:
        measure("backend", "api", "POST", BACKEND, path, "guest", body=body)

    hub = os.environ.get("PROBE_HUB_ID", "").strip()
    mock = os.environ.get(
        "PROBE_MOCK_ID", "a0000000-0000-4000-8000-000000000001"
    ).strip()
    if hub:
        for path in (
            f"/api/practice/hubs/{hub}",
            "/api/practice/mock-unlock?skill=listening",
        ):
            measure("backend", "api", "GET", BACKEND, path, auth_mode)
    if mock:
        for path in (
            f"/api/tests/{mock}/questions",
            f"/api/listening/{mock}/questions",
            f"/api/reading/{mock}/questions",
            f"/api/speaking/{mock}/eligibility",
        ):
            measure("backend", "api", "GET", BACKEND, path, auth_mode)

    for path in FRONTEND_PAGES:
        measure("frontend", "page", "GET", FRONTEND, path, auth_mode)

    for method, path in FRONTEND_BFF:
        measure("frontend", "bff", method, FRONTEND, path, auth_mode)

    admin_auth = auth_mode if auth_mode in {"user", "admin"} else "public"
    for path in ADMIN_PAGES:
        measure("admin", "page", "GET", ADMIN, path, admin_auth)

    for method, path in ADMIN_BFF:
        measure("admin", "bff", method, ADMIN, path, admin_auth)

    result = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "bases": {"frontend": FRONTEND, "backend": BACKEND, "admin": ADMIN},
        "auth_mode": auth_mode,
        "auth_email": email or None,
        "guest_probe_ok": guest_ok,
        "samples": [asdict(s) for s in samples],
        "summary": _summarize(samples),
    }
    text = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
            f.write("\n")
        print(f"Wrote {args.out} ({len(samples)} samples)", file=sys.stderr)
    else:
        print(text)
    return 0


def _summarize(samples: list[Sample]) -> dict[str, Any]:
    by_app: dict[str, list[Sample]] = {}
    for s in samples:
        by_app.setdefault(s.app, []).append(s)

    def bucket(rows: list[Sample]) -> dict[str, Any]:
        ok = [r for r in rows if 200 <= r.status < 400]
        slow = [r for r in ok if r.client_ms >= 2000]
        warn = [r for r in ok if 1000 <= r.client_ms < 2000]
        return {
            "count": len(rows),
            "ok": len(ok),
            "errors": len(rows) - len(ok),
            "p50_ms": _pct([r.client_ms for r in ok], 50),
            "p95_ms": _pct([r.client_ms for r in ok], 95),
            "slow_ge_2s": len(slow),
            "warn_ge_1s": len(warn),
            "slowest": sorted(
                [
                    {
                        "path": r.path,
                        "method": r.method,
                        "status": r.status,
                        "client_ms": r.client_ms,
                        "server_ms": r.server_ms,
                        "kind": r.kind,
                    }
                    for r in ok
                ],
                key=lambda x: -x["client_ms"],
            )[:10],
        }

    return {app: bucket(rows) for app, rows in by_app.items()}


def _pct(vals: list[float], p: int) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    idx = min(len(s) - 1, max(0, int(round((p / 100) * (len(s) - 1)))))
    return s[idx]


if __name__ == "__main__":
    raise SystemExit(main())
