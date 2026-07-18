# Writing calibration baselines

| File | Mode | Notes |
|------|------|-------|
| `writing-v5-stub-baseline.json` | Stub | Schema/JSON gate only — bands are always ~6.0 |
| `writing-v5-baseline.json` | Live | Generated 2026-07-15 — **did not pass MAE/agreement gates** (see below) |

Always use the project venv (system Python lacks `pydantic`):

```bash
cd backend
source .venv/bin/activate

# Stub (no API cost)
WRITING_EVAL_STUB=true WRITING_LLM_PRIMARY=none \
  python scripts/evaluate_fixture.py --all --calibrate --no-cache

# Live (costs credits)
WRITING_EVAL_STUB=false WRITING_LLM_PRIMARY=claude WRITING_LLM_FALLBACK=none \
  python scripts/evaluate_fixture.py --all --live --calibrate --no-cache \
  --json-report docs/calibration/writing-v5-baseline.json
```

**Acceptance (live):** JSON validity 100%, overall MAE ≤ 0.5, agreement within ±0.5 ≥ 80%.

### Live run notes (2026-07-15)

- JSON validity: **100%** (pass)
- Overall MAE: **0.95** (fail, need ≤ 0.5)
- Agreement ±0.5: **25%** (fail, need ≥ 80%)
- Many fixtures scored via **Groq fallback** (`llama-3.3-70b-versatile`), which trended high vs gold labels
- Re-run with `WRITING_LLM_FALLBACK=none` so only Claude is measured, then tune v5 prompt if MAE still fails
