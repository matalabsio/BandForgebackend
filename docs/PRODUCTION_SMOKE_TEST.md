# Production smoke-test runbook

Repeatable pre-launch / post-deploy validation. **Do not ship if any Critical check fails.**

| Field | Value |
| --- | --- |
| Date | |
| Deploy / commit | |
| Tester | |
| Environment URL (web) | |
| API base URL | |
| Result | ☐ Pass · ☐ Fail · ☐ Pass with notes |

---

## Preconditions

- [ ] Target deploy is the intended commit (migrations already applied for this release).
- [ ] Razorpay **Live** (or intentional Test) mode matches the keys in the environment.
- [ ] Use a **throwaway** account for purchase / refund checks when possible.
- [ ] Admin account available for `is_free` toggle.
- [ ] Browser: one normal window + one private/incognito for guest diagnostic.

---

## 0. Production surface (Critical)

Run against the **API base URL**:

```bash
# Expect 200 + {"status":"ok"} (or equivalent healthy body)
curl -sS -o /tmp/bf-health.json -w "%{http_code}\n" "$API/health"
cat /tmp/bf-health.json

# Expect 404 (or non-200 docs body) in production when ENABLE_API_DOCS is off
curl -sS -o /dev/null -w "%{http_code}\n" "$API/docs"
curl -sS -o /dev/null -w "%{http_code}\n" "$API/redoc"
curl -sS -o /dev/null -w "%{http_code}\n" "$API/openapi.json"

# Expect 404 in production
curl -sS -o /dev/null -w "%{http_code}\n" "$API/api/tests/db-check"
curl -sS -o /dev/null -w "%{http_code}\n" "$API/api/tests/r2-check"
```

- [ ] `GET /health` succeeds
- [ ] `GET /docs` unavailable
- [ ] `GET /redoc` unavailable
- [ ] `GET /openapi.json` unavailable
- [ ] `GET /api/tests/db-check` unavailable
- [ ] `GET /api/tests/r2-check` unavailable

---

## 1. Authentication (Critical)

- [ ] Email signup (or login with existing test user)
- [ ] Email login
- [ ] Google OAuth login → lands on intended `next` path
- [ ] Logout clears session (dashboard redirects to login)
- [ ] Hard refresh while logged in keeps session
- [ ] Session refresh: wait for access expiry **or** clear access cookie only → app recovers via refresh (no forced logout loop)
- [ ] Expired refresh → clean login redirect (no crash)

**Pass if:** user can reach dashboard after each successful auth path; logout is sticky.

---

## 2. Diagnostic (Critical)

**Guest (incognito)**

- [ ] Start free diagnostic without account
- [ ] Complete at least one module path through plan reveal / results
- [ ] Prompted to login/signup where expected

**Logged-in**

- [ ] Complete or resume diagnostic while authenticated
- [ ] Results appear on dashboard after sync (no empty “never ran” state for completed run)

**Pass if:** guest funnel works; logged-in sync shows on dashboard.

---

## 3. Payments & entitlements (Critical)

Use Live/Test cards or UPI per Razorpay mode. Keep payment IDs in notes.

| Step | Check | Payment / order ID |
| --- | --- | --- |
| Buy M1 path (or Full Skill / plan that unlocks M1) | [ ] | |
| Subscription shows **active** on success + billing | [ ] | |
| Start M1 module (listening or reading) | [ ] Allowed | |
| Buy / renew second plan (stacking) | [ ] New window starts after current expiry | |
| Kill network mid-verify → reload `/checkout/success` | [ ] Recovers or clear error (no silent loss) | |
| Modal **Try again** after verify failure | [ ] Re-verify works | |
| Duplicate verify (same Razorpay payload twice) | [ ] Idempotent; still one entitlement | |
| Duplicate webhook (replay same `event_id`) | [ ] Idempotent; no double sub | |
| Full refund (Razorpay dashboard) | [ ] Sub cancelled; paid mocks blocked | |
| Partial refund (if available) | [ ] Sub **stays** active | |

Also:

- [ ] Free user **cannot** start M1/M2 (`402` / paywall UI)
- [ ] Diagnostic remains free without subscription

**Pass if:** capture grants access; refunds behave as above; duplicates do not double-fulfill.

---

## 4. Practice modules (High)

With an entitled account:

- [ ] Listening: start → answer → submit → score/pending path
- [ ] Reading: start → submit → score path
- [ ] Writing: submit Task 1 (and Task 2 if applicable) → pending/results
- [ ] Speaking: mic check → record → upload → finalize → pending → report when ready

**Pass if:** no stuck busy state; oversized speaking upload rejected cleanly if tested; report/pending reachable.

---

## 5. Admin entitlements (High)

- [ ] Admin opens mock detail → toggle **Mark as free/paid**
- [ ] Free toggle: non-subscriber can start that mock immediately
- [ ] Paid toggle: free user blocked again immediately
- [ ] Diagnostic stays free unless intentionally changed

---

## 6. Configuration review (before open traffic)

Confirm in the **production** host (Railway / secrets UI)—do not paste secrets into this doc.

| Variable / area | OK |
| --- | --- |
| `APP_ENV=production` | [ ] |
| JWT access + refresh secrets set, long, unique | [ ] |
| Razorpay Live key id + secret (or intentional test) | [ ] |
| Razorpay webhook secret matches dashboard | [ ] |
| Google OAuth client + redirect URIs | [ ] |
| `ENABLE_API_DOCS` off (or explicitly justified) | [ ] |
| `TRUST_X_FORWARDED_FOR` matches proxy setup | [ ] |
| Supabase URL + service role | [ ] |
| R2 credentials + bucket | [ ] |
| Background / worker process running if required | [ ] |
| Frontend `NEXT_PUBLIC_*` API / app URLs | [ ] |

---

## 7. Monitoring readiness (before open traffic)

Confirm you can see or alert on:

- [ ] Payment verify failures
- [ ] Webhook failures / 503 retries
- [ ] OAuth / auth 5xx
- [ ] Speaking evaluation / job failures
- [ ] API 5xx rate
- [ ] Upload / R2 failures

Note where each is visible (Railway logs, provider dashboard, etc.):

| Signal | Where to look |
| --- | --- |
| Payments | |
| Webhooks | |
| Auth | |
| Jobs | |
| API 5xx | |

---

## Sign-off

- [ ] All **Critical** sections passed
- [ ] High sections passed or waived with reason
- [ ] No open Sev-1/Sev-2 from this run

**Waivers / notes**

```
(notes)
```

**Go / no-go:** ☐ Launch · ☐ Hold
