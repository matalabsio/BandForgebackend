#!/usr/bin/env python3
"""Probe Frontend page route response times (Next.js wall clock).

Expands dynamic segments to concrete URLs, warms once, then measures.
Supports Google-auth via TEST_EMAIL (session mint) or BF_ACCESS.

Usage:
  cd backend
  TEST_EMAIL=arsh8795737563@gmail.com .venv/bin/python scripts/probe_frontend_route_times.py \\
    --warm --out ../docs/frontend-route-times.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from probe_all_route_times import (  # noqa: E402
    FRONTEND,
    Client,
    mint_session_for_email,
    probe,
)

FRONTEND_APP = Path(__file__).resolve().parents[2] / "frontend" / "app"

# Concrete stand-ins for dynamic segments (local catalog / known hubs)
SKILLS = ("listening", "reading", "writing", "speaking")
HUBS = {
    "listening": os.environ.get(
        "PROBE_HUB_LISTENING", "d9bdd248-29ed-423c-8b5f-58637454f647"
    ),
    "reading": os.environ.get(
        "PROBE_HUB_READING", "fc59673f-b5b0-46f6-88ef-fa8078e05b98"
    ),
    "writing": os.environ.get(
        "PROBE_HUB_WRITING", "b8ed187d-b082-465f-beb7-c8e89e247251"
    ),
    "speaking": os.environ.get(
        "PROBE_HUB_SPEAKING", "b8ed187d-b082-465f-beb7-c8e89e247251"
    ),
}
MOCK_SLUG = os.environ.get("PROBE_MOCK_SLUG", "m01")
TEST_NUMBER = os.environ.get("PROBE_TEST_NUMBER", "1")
BLOG_SLUG = os.environ.get("PROBE_BLOG_SLUG", "ielts-band-score")
DIAG_TRANSITION = os.environ.get("PROBE_DIAG_TRANSITION", "listening-to-reading")
ATTEMPT_ID = os.environ.get(
    "PROBE_ATTEMPT_ID", "00000000-0000-4000-8000-000000000001"
)


def discover_templates() -> list[str]:
    routes: set[str] = set()
    for p in FRONTEND_APP.rglob("page.tsx"):
        rel = p.relative_to(FRONTEND_APP).as_posix()
        parts = [x for x in rel[: -len("/page.tsx")].split("/") if x]
        parts = [x for x in parts if not (x.startswith("(") and x.endswith(")"))]
        path = "/" + "/".join(parts) if parts else "/"
        routes.add(path)
    return sorted(routes)


def expand(template: str) -> list[str]:
    """Turn /practice/[skill]/[hubId] into concrete URLs."""
    if "[" not in template:
        return [template]

    out: list[str] = []

    if template.startswith("/practice/"):
        for skill in SKILLS:
            path = template.replace("[skill]", skill)
            if "[hubId]" in path:
                path = path.replace("[hubId]", HUBS.get(skill, HUBS["listening"]))
            out.append(path)
        return out

    if template.startswith("/mock/"):
        path = template.replace("[mockSlug]", MOCK_SLUG)
        return [path]

    if template.startswith("/test/[number]"):
        path = template.replace("[number]", TEST_NUMBER)
        return [path]

    if template == "/test/writing/task/[part]":
        return ["/test/writing/task/1", "/test/writing/task/2"]

    if template.startswith("/test/") and "[attemptId]" in template:
        return [template.replace("[attemptId]", ATTEMPT_ID)]

    if template == "/blog/[slug]":
        return [f"/blog/{BLOG_SLUG}"]

    if template == "/diagnostic/transition/[slug]":
        return [f"/diagnostic/transition/{DIAG_TRANSITION}"]

    # Unknown dynamic — skip rather than probe a broken URL
    return []


def all_concrete_routes() -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for tmpl in discover_templates():
        for path in expand(tmpl):
            if path not in seen:
                seen.add(path)
                ordered.append(path)
    return ordered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--warm", action="store_true")
    parser.add_argument("--samples", type=int, default=1)
    args = parser.parse_args()

    email = os.environ.get("TEST_EMAIL", "").strip()
    bf_access = os.environ.get("BF_ACCESS", "").strip()

    client = Client()
    auth_mode = "public"
    if bf_access:
        client.set_bearer(bf_access)
        auth_mode = "user"
    elif email:
        minted = mint_session_for_email(email)
        if minted:
            access, refresh, role = minted
            client.set_bearer(access)
            client.set_auth_cookies(access=access, refresh=refresh)
            auth_mode = "admin" if role in {"admin", "super_admin"} else "user"
        else:
            print("WARN: session mint failed; probing as public", file=sys.stderr)

    routes = all_concrete_routes()
    print(f"Probing {len(routes)} frontend routes (auth={auth_mode})", file=sys.stderr)

    if args.warm:
        for path in ("/", "/login", "/pricing", "/dashboard"):
            probe(
                client,
                app="frontend",
                kind="page",
                method="GET",
                base=FRONTEND,
                path=path,
                auth=auth_mode,
            )

    samples = []
    for path in routes:
        times = []
        for _ in range(max(1, args.samples)):
            times.append(
                probe(
                    client,
                    app="frontend",
                    kind="page",
                    method="GET",
                    base=FRONTEND,
                    path=path,
                    auth=auth_mode,
                )
            )
        times.sort(key=lambda s: s.client_ms)
        mid = times[len(times) // 2]
        samples.append(
            {
                "path": path,
                "status": mid.status,
                "ms": mid.client_ms,
                "auth": mid.auth,
                "note": mid.note,
            }
        )
        mark = "OK" if 200 <= mid.status < 400 else f"ERR{mid.status}"
        print(f"  {mid.client_ms:8.1f}ms  {mark:6}  {path}", file=sys.stderr)

    ok = [s for s in samples if 200 <= s["status"] < 400]
    slow = [s for s in ok if s["ms"] >= 2000]
    warn = [s for s in ok if 1000 <= s["ms"] < 2000]

    def pct(vals: list[float], p: int) -> float | None:
        if not vals:
            return None
        s = sorted(vals)
        return s[min(len(s) - 1, max(0, int(round((p / 100) * (len(s) - 1)))))]

    result = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "base": FRONTEND,
        "auth_mode": auth_mode,
        "auth_email": email or None,
        "route_count": len(samples),
        "summary": {
            "ok": len(ok),
            "errors": len(samples) - len(ok),
            "p50_ms": pct([s["ms"] for s in ok], 50),
            "p95_ms": pct([s["ms"] for s in ok], 95),
            "slow_ge_2s": len(slow),
            "warn_ge_1s": len(warn),
            "slowest": sorted(ok, key=lambda x: -x["ms"])[:20],
        },
        "samples": samples,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out} ({len(samples)} routes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
