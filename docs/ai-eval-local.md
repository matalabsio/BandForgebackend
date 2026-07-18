# AI evaluation — local / offline development

BandForge writing and speaking AI pipelines support **stub mode** so day-to-day work costs $0 in Anthropic/Groq credits.

## Architecture map (Phase 1–10)

| Roadmap name | Implementation |
|--------------|----------------|
| Stub / offline | `WRITING_EVAL_STUB` → `StubWritingProvider`; `SPEAKING_EVAL_STUB` → stub ASR/eval |
| ClaudeProvider | Writing + speaking providers under `app/*/providers/` |
| Prompt Loader | Writing: `prompt_loader.py` + `prompts/v5/` (v4 locked). Speaking: `speaking_prompt.py` |
| Response Parser / Retry | `evaluation_call.py` (writing + speaking) |
| Shared cache | Writing: `app/writing/eval_cache.py` |
| Budget / circuit / metrics | `app/ai_ops/` |
| Speaking student report | `GET /api/speaking/attempts/{id}/report` → `buildSpeakingFeedback` UI |
| AI Dashboard | Admin `/admin/ai` → `GET /admin/ai/metrics` |
| Human review / analytics | Queue → AI vs human compare → approve snapshot → `/admin/review-analytics` |
| Golden / calibration QA | `tests/essays` + `evaluate_fixture.py --calibrate` + `WRITING_PROMPT_VERSION` |
| Learning intelligence | `user_learning_profiles` + `app/learning/` + `/api/learning/*` |
| AI Learning Assistant | `app/tutor/` + `/api/tutor/chat` on writing results |

Business logic (diagnostic / mock / CLI) calls `evaluate_writing_essay()` only — never Claude directly.

### Prompt versions

- **v4** — frozen under `app/writing/prompts/v4/` (do not edit); kept for comparison / replay
- **v5** — default (`DEFAULT_PROMPT_VERSION`); adds `next_band_advice`, `confidence`, `vocabulary_highlights`, `strong_spans`

Cached **v4** rows still load: missing v5 fields coerce to empty / `confidence=0.5`.

After stub verifies schema locally, run curated essays live to validate score quality:

```bash
WRITING_EVAL_STUB=false WRITING_LLM_PRIMARY=claude \
  python scripts/evaluate_fixture.py --all --live --no-cache
```

Human calibration of 20–30 essays remains a manual QA ops task after merge.

### Acceptance thresholds (Phase 8)

| Metric | Gate |
|--------|------|
| JSON validity on golden set | **100%** |
| Overall band MAE (live) | **≤ 0.5** |
| Agreement within ±0.5 band (live) | **≥ 80%** |

Golden set: `backend/tests/essays/manifest.json` (**20** labeled fixtures, each with `expected_overall` + `expected_criteria`).

Record live baselines under `backend/docs/calibration/` (gitignored if preferred) via:

```bash
WRITING_EVAL_STUB=false WRITING_LLM_PRIMARY=claude \
  python scripts/evaluate_fixture.py --all --live --calibrate --no-cache \
  --json-report docs/calibration/writing-v5-baseline.json
```

Ship prompt/model changes only when the live report meets the thresholds above.

## Defaults

In `backend/.env.local` (loaded over `.env` when `APP_ENV` is not `production`):

```bash
WRITING_EVAL_STUB=true
SPEAKING_EVAL_STUB=true
WRITING_LLM_PRIMARY=none
WRITING_LLM_FALLBACK=none

# Phase 3 — keep Claude live usage low if stub is flipped off
CLAUDE_DAILY_LIMIT=20
CLAUDE_MONTHLY_LIMIT=100
CLAUDE_WARNING_AT=16
AI_BUDGET_FALLBACK_STUB=true
```

With writing stub on, `evaluate_writing_essay()` never enters Claude or Groq branches. Diagnostic and mock paths still return full schema-valid feedback (including sample spelling/grammar mistakes for UI annotation paths).

## Commands

```bash
cd backend
source .venv/bin/activate

# Writing stub smoke
python scripts/writing_eval_smoke.py

# Curated fixtures (stub + shared essay_hash cache)
python scripts/evaluate_fixture.py --all
python scripts/evaluate_fixture.py task2_band6.txt

# Speaking stub smoke
python scripts/speaking_eval_smoke.py
```

Fixtures live in `backend/tests/essays/` with `manifest.json`.

## Intentional live Claude

Keys (either name works):

```bash
ANTHROPIC_API_KEY=sk-ant-...
# or
CLAUDE_API_KEY=sk-ant-...

WRITING_EVAL_TIMEOUT_SEC=120
ANTHROPIC_MODEL=claude-sonnet-4-6
```

Live session (opt in explicitly):

```bash
# In .env.local, for a short validation session only:
WRITING_EVAL_STUB=false
WRITING_LLM_PRIMARY=claude
WRITING_LLM_FALLBACK=none

python scripts/evaluate_fixture.py task2_band6.txt --live --no-cache
# --live refuses to run if WRITING_EVAL_STUB is still true
```

Do **not** run live Claude in CI.

### Phase 2 live checklist

1. Stub off + `WRITING_LLM_PRIMARY=claude`
2. Key present (`ANTHROPIC_API_KEY` or `CLAUDE_API_KEY`, or AWS Claude platform vars)
3. Fixture CLI succeeds with `provider=anthropic_claude`
4. Persisted `raw_ai_response.request` contains `prompt_version`, `model`, `essay_word_count`, `requested_at`
5. Re-run same fixture without `--no-cache` → cache hit (no second Claude call)

## Phase 3 — ops

Pre-call logs (no essay body) include estimated tokens/cost. Daily/monthly **eval-count** budgets for Claude; when exceeded (or circuit open), factory skips Claude → Groq → stub (`AI_BUDGET_FALLBACK_STUB`).

Admin UI: **Admin → AI ops** (`/admin/ai`) for calls, est. cost, latency, success/retry rates, budget remaining, circuit state, recent failures, speaking pending/failed counts.

```bash
# Production-oriented limits (override in deploy env)
CLAUDE_DAILY_LIMIT=200
CLAUDE_MONTHLY_LIMIT=2000
AI_CIRCUIT_FAIL_THRESHOLD=5
AI_CIRCUIT_COOLDOWN_SEC=300
AI_INPUT_USD_PER_MTOK=3.0
AI_OUTPUT_USD_PER_MTOK=15.0
```

## Shared cache

Evaluations are keyed by `sha256(task_part + normalized question + normalized essay)` in `diagnostic_ai_evaluations`. Mock, diagnostic, and the fixture CLI share this table. Sources `ai` and `ai_stub` are cacheable; `fallback` rows are never reused.

## Exit criteria

### Phase 1 (offline)

- Complete AI writing path works with stubs and no LLM network calls
- Claude only runs when stub is explicitly disabled
- Re-evaluating the same fixture is a cache hit

### Phase 2 (Claude integration)

- Claude evaluates essays only through `ClaudeWritingProvider` → factory
- Diagnostic/mock/CLI remain provider-agnostic (stub | claude | groq)
- Prompts load from versioned files under `writing/prompts/`
- Keys stay env-only; `CLAUDE_API_KEY` alias works
- Timeouts (`WRITING_EVAL_TIMEOUT_SEC`) and retries remain enforced; raw responses store request metadata

### Phase 3 (ops)

- Pre-call token/cost logging for live writes
- Daily/monthly Claude eval budgets enforced with Groq→stub fallback
- Admin `/admin/ai` shows cost, latency, success rate, retries, provider availability
- Circuit breaker opens Claude after repeated failures

### Phase 4 (eval engine v5)

- Default prompt **v5** with next-band, confidence, vocab highlights, strong spans
- **v4** prompt files locked (untouched)
- Writing feedback UI prefers AI next-band / vocab / strong spans when present
- Stub + unit tests cover extended schema; cached v4 evaluations still coerce cleanly

### Phase 5 (speaking student report)

Speaking ASR → fluency metrics → LLM JSON already runs on submit (`SPEAKING_EVAL_STUB` for offline). Student report is human-gated:

1. Submit speaking → background eval writes `transcript` + `ai_scores.evaluation`
2. Admin approves with `human_band` (+ optional `human_criteria_scores`)
3. Student: `GET /api/speaking/attempts/{id}/pending` (poll) then `GET /api/speaking/attempts/{id}/report` (rich payload)
4. Frontend `buildSpeakingFeedback` prefers human criteria / AI evaluation; heuristics only when empty
5. Report UI: criteria, part cards, annotated transcript (evidence highlights), fluency tiles, patterns, strengths/advice

```bash
# Offline stub eval smoke
python scripts/speaking_eval_smoke.py

# Report unit tests
python -m pytest tests/speaking/test_speaking_report.py -q
```

`/report` returns **409** until `human_band` is set. No DB migration — uses existing jsonb + transcript columns.

### Phase 6 (interactive annotations)

Grammarly-like feedback inside student responses:

- Shared `AnnotatedText` + `AnnotationPopover` (hover on fine pointer, tap/click toggle, Escape/outside close)
- Writing: merged highlights (strong spans → spelling → grammar → vocab) with `title` / `detail` / `suggestion` for popovers
- Speaking: evidence + pronunciation-styled marks; `pause_markers` derived from stored ASR `words` on `/report` (not a full word dump)
- Side lists remain; heuristics only when AI payloads are empty

Speaking pause markers require `ai_scores.words` (Whisper timestamps). Stub mode may return empty pauses unless timings are present.

### Phase 7 (human review & moderation)

Trainer path without rebuilding queues:

1. **Queue** — pending rows show AI band for triage
2. **Compare** — detail workspace shows AI vs human deltas, Accept AI, highlight criteria ≥ 0.5 from AI
3. **Approve** — audit metadata snapshots `ai_band` / `ai_criteria`, `overridden`, `delta_overall`
4. **Student writing** — `human_verified` + `reviewer_notes` on review response (parity with speaking)
5. **History** — `GET /admin/speaking|{writing}/{id}/history` timeline on detail pages
6. **Analytics** — `GET /admin/review-analytics` + `/admin/review-analytics` (agreement, override rate, criterion MAE)

```bash
python -m pytest tests/admin/test_review_phase7.py -q
```

### Phase 8 (AI quality assurance)

Make prompt/model changes **measurable and safe** (writing-focused):

1. **Golden set** — `tests/essays/manifest.json` with `expected_overall` + `expected_criteria` (~20 fixtures; expand further with examiner labels)
2. **Calibration** — `app/writing/calibration.py` (MAE, agreement, band consistency, JSON validity)
3. **CLI** — `evaluate_fixture.py --calibrate [--prompt-version v4|v5] [--json-report path]`
4. **Prompt/model versioning** — `WRITING_PROMPT_VERSION` (alias `DIAGNOSTIC_WRITING_PROMPT_VERSION`); essay hash includes prompt + model so cache cannot cross versions
5. **CI regressions** — `tests/writing/test_golden_manifest.py`, `test_json_consistency.py`, `test_calibration_stub.py`, `test_prompt_regression.py`, `test_model_pin.py`
6. **Acceptance** — live gate: JSON validity 100%, overall MAE ≤ 0.5, ±±0.5 ≥ 80%

```bash
# Stub: schema + JSON validity gate (band gates off in stub unless --force-band-gates)
python scripts/evaluate_fixture.py --all --calibrate --no-cache

# Prompt A/B (stub)
python scripts/evaluate_fixture.py --all --calibrate --prompt-version v4 --json-report /tmp/v4.json
python scripts/evaluate_fixture.py --all --calibrate --prompt-version v5 --json-report /tmp/v5.json

# Pre-merge live gold gate (costs credits)
WRITING_EVAL_STUB=false WRITING_LLM_PRIMARY=claude \
  python scripts/evaluate_fixture.py --all --live --calibrate --no-cache

# Unit suites
python -m pytest tests/writing/test_golden_manifest.py tests/writing/test_json_consistency.py \
  tests/writing/test_calibration_stub.py tests/writing/test_prompt_regression.py \
  tests/writing/test_model_pin.py tests/writing/test_calibration_unit.py -q
```

**Model upgrade checklist:** change `ANTHROPIC_MODEL` → live calibrate with `--no-cache` → expect cache miss (hash includes model) → ship only if agreement/MAE acceptable.

Speaking golden transcripts remain a follow-up; existing speaking schema unit tests still apply.

### Phase 9 (learning intelligence)

Turn evaluations into a persisted adaptive profile + rule-based study plan (no LLM plan generator).

**Table:** `user_learning_profiles` (service-role writes; RLS enabled, no client policies)

**Engine:** `app/learning/` — ingest → aggregate → rules → upsert

| Endpoint | Role |
|----------|------|
| `GET /api/learning/profile` | Ensure profile exists; refresh if stale (>24h or new ISO week) |
| `POST /api/learning/refresh` | Force recompute |
| `PATCH /api/learning/tasks/{task_id}` | Mark plan task `pending`/`done`/`skipped` |

**Refresh triggers**
- Lazy on GET/refresh
- Eager (background thread): writing approve, speaking approve, L/R `submit_attempt` after `persist_module_submit_bundle`

**Student UI**
- Dashboard Today’s plan, `/study-plan`, scores insights, performance chart target band
- Writing/speaking feedback builders take `users.target_band`

```bash
python -m pytest tests/learning/ -q
```

### Phase 10 (AI learning assistant)

Writing-first conversational tutor grounded in the student’s essay + evaluation (not generic tips).

**Engine:** `app/tutor/` — context pack → prompts → stub or writing LLM providers (`chat_json`) + Claude budget gates

| Endpoint | Role |
|----------|------|
| `POST /api/tutor/chat` | Owned writing `attempt_id` + message (+ optional selection / turns) |
| `GET /api/tutor/suggestions` | Suggested chips (static + weakness/grammar from context) |

**Context pack (server-built every turn)**
- Current essay, criteria, strengths/improvements, grammar mistakes, weak vocab, next-band advice
- Up to 2 prior writing attempts (band + criteria + improvements)
- Slim Phase 9 profile (`target_band`, top weaknesses, grammar/vocab stats)

**Stub:** when `WRITING_EVAL_STUB=true`, replies quote the student’s band / mistakes / vocab (deterministic). Turns stored client-side (`sessionStorage`).

**UI:** “Ask coach” panel on writing feedback; dashboard AI Coach CTA → latest writing results `?coach=1`.

```bash
python -m pytest tests/tutor/ -q
```
