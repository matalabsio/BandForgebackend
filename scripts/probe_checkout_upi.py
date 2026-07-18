#!/usr/bin/env python3
"""Open Razorpay Standard Checkout for a Test order and report whether UPI is visible.

Requires: backend running on :8000, Playwright Chromium (system Python with playwright).

Usage:
  PYTHONPATH=. .venv/bin/python scripts/probe_checkout_upi.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.auth.jwt import create_access_token
from app.config import reload_settings
from app.db import get_supabase


def _api(method: str, path: str, token: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:8000{path}",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw) if raw else {}
        except Exception:
            return exc.code, {"raw": raw[:400]}


def _pick_smoke_user() -> tuple[str, str]:
    sb = get_supabase()
    res = (
        sb.table("users")
        .select("id,email")
        .ilike("email", "smoke.w0.%@matalabs.io")
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if rows:
        return str(rows[0]["id"]), str(rows[0]["email"])
    res = sb.table("users").select("id,email").limit(1).execute()
    rows = res.data or []
    if not rows:
        raise SystemExit("No users in DB to mint a checkout probe JWT.")
    return str(rows[0]["id"]), str(rows[0]["email"])


def main() -> int:
    reload_settings()
    s = reload_settings()
    cfg = (s.razorpay_checkout_config_id or "").strip()
    print("checkout_config_id:", (cfg[:14] + "…") if cfg else "(unset)")

    user_id, email = _pick_smoke_user()
    token = create_access_token(user_id=user_id, email=email)
    code, order = _api(
        "POST", "/api/payments/create-order", token, {"plan_slug": "full_skill_program"}
    )
    if code != 200:
        print("create-order failed", code, order)
        return 1
    print("order_id:", order.get("order_id"))
    print("create_order.checkout_config_id:", order.get("checkout_config_id") or "(null)")

    contact = order.get("checkout_contact") or {}
    html = f"""<!doctype html><html><body>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<script>
var opts = {{
  key: {json.dumps(order["key_id"])},
  amount: String({int(order["amount"])}),
  currency: "INR",
  name: "BandForge UPI Probe",
  order_id: {json.dumps(order["order_id"])},
  prefill: {{
    name: {json.dumps(contact.get("name") or "Probe")},
    email: {json.dumps(contact.get("email") or email)},
    contact: "9883288356"
  }},
  method: {{ upi: true, card: true, netbanking: true, wallet: true, paylater: false }},
  remember_customer: false,
  handler: function() {{}}
}};
var cid = {json.dumps((order.get("checkout_config_id") or "").strip() or None)};
if (cid) {{
  opts.checkout_config_id = cid;
}} else {{
  opts.config = {{
    display: {{
      blocks: {{
        upi_preferred: {{
          name: "Pay using UPI",
          instruments: [{{ method: "upi", flows: ["qr", "intent"] }}]
        }}
      }},
      sequence: ["block.upi_preferred", "upi", "card", "netbanking", "wallet"],
      hide: [{{ method: "paylater" }}],
      preferences: {{ show_default_blocks: true }}
    }}
  }};
}}
new Razorpay(opts).open();
</script></body></html>"""

    tmp = Path(tempfile.mkdtemp(prefix="bf_upi_probe_"))
    (tmp / "index.html").write_text(html)
    os.chdir(tmp)
    httpd = ThreadingHTTPServer(("127.0.0.1", 8799), SimpleHTTPRequestHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Playwright not installed in this Python. "
            "Install playwright or open /pricing manually to verify UPI.",
            file=sys.stderr,
        )
        httpd.shutdown()
        return 3

    upi_visible = False
    methods_seen: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto("http://127.0.0.1:8799/index.html", wait_until="domcontentloaded")
        body = ""
        for _ in range(60):
            chunks: list[str] = []
            for frame in page.frames:
                try:
                    chunks.append(frame.locator("body").inner_text(timeout=400))
                except Exception:
                    continue
            body = "\n".join(chunks)
            lower = body.lower()
            if "payment options" in lower and (
                "netbanking" in lower or "cards" in lower or "upi" in lower
            ):
                break
            time.sleep(0.4)
        lower = body.lower()
        for label in ("upi", "cards", "card", "netbanking", "wallet", "pay later", "qr"):
            if label in lower:
                methods_seen.append(label)
        upi_visible = "upi" in lower
        page.screenshot(path=str(tmp / "checkout.png"), full_page=True)
        browser.close()
    httpd.shutdown()

    print("methods_seen:", methods_seen)
    print("upi_visible:", upi_visible)
    print("screenshot:", tmp / "checkout.png")
    if "netbanking" not in methods_seen and "cards" not in methods_seen and "card" not in methods_seen:
        print("FAIL: Checkout did not load payment methods (stuck on splash?).")
        return 2
    if not upi_visible:
        print(
            "FAIL: UPI not visible (saw: %s). Complete Dashboard Payment Configuration "
            "(UPI Apps+QR), Save as Default, set RAZORPAY_CHECKOUT_CONFIG_ID, restart."
            % (", ".join(methods_seen) or "none")
        )
        return 1
    print("PASS: UPI appears in Checkout.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
