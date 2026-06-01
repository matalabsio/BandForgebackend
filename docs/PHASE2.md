# Phase 2 — Fewer DB round-trips

## Applied in code

1. **`get_mock_start_context` RPC** (`20260601120000_mock_start_context_rpc.sql`)
   - Returns `mock_test`, `modules`, `in_progress_attempt` in one HTTP call.
   - Fallback: sequential `get_mock_test` + `list_mock_modules` + `find_in_progress`.

2. **`start_mock` optimization**
   - Uses start context RPC once.
   - One `get_mock_attempt_progress` bundle for target selection.
   - After module start: updates progress **in memory** (no second `get_progress` / bundle fetch).
   - Writes fresh progress into Redis (`mock_progress` + `mock_session`).

3. **Narrow cache invalidation** (`app/cache/mock_cache.py`)
   - Module start/submit invalidates only progress/session/in-progress keys.
   - **`listening_questions` / `reading_questions` stay cached** across submits.

4. **Writing page** — single `start` POST (no Strict Mode double boot).

## Apply migration

**Cloud:** already applied via Supabase MCP, or run SQL from migration file in dashboard.

**Local:**

```bash
cd backend
./scripts/local_supabase.sh reset   # reapplies all migrations including Phase 2
```

## Verify

```bash
cd backend && PYTHONPATH=. .venv/bin/pytest tests/test_mock_orchestrator.py -q
```

Measure `POST /api/mock-attempts` `duration_ms` before/after (with local Supabase for clearest signal).

## Phase 2b — submit bundle (done)

Migration: `20260601140000_module_submit_bundle_rpc.sql`

- **`persist_module_submit_bundle` RPC** — answers upsert + `test_attempts` complete + `module_scores` in **one** transaction.
- Python: `app/db/module_submit_bundle.py` with sequential fallback.
- Wired into listening / reading / writing `submit_attempt`.
- **`on_module_attempt_completed`** — accepts completed `attempt` row (skips re-fetch); one progress bundle + cache warm at end.

Apply on local: `./scripts/local_supabase.sh reset` (after `supabase start`).

## Next

- Optional `get_dashboard_bundle` RPC.
