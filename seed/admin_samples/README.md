# Admin dashboard — sample JSON for ingest tests

Use these in **Admin → Mocks → [mock] → Ingest**.

## Mock IDs

| Mock | UUID |
|------|------|
| Academic Mock 1 (MT1) | `a0000000-0000-4000-8000-000000000001` |
| Academic Mock 2 (MT2) | `a0000000-0000-4000-8000-000000000002` |

Tests 3–5 are **upcoming** in the candidate app (placeholders only). Admin drafts may exist in the DB but are not exposed to learners until promoted to a live slot (Test 1 or Test 2).

## Quick smoke test (mini files)

| File | Module | Part | Questions |
|------|--------|------|-----------|
| `reading_mini.json` | reading | 1 | 5 |
| `listening_mini.json` | listening | 1 | 4 |

### Steps

1. Sign in at `/admin/login`
2. Open **Mocks** → pick **IELTS Academic Mock 2**
3. **Ingest** → module **reading**, part **1** → paste `reading_mini.json` → **Validate & preview** → **Publish**
4. Repeat with module **listening**, part **1**, `listening_mini.json`, and set audio key e.g. `listening/m02/part-1/full.mp3`

## Full production-shaped files (repo)

| Path | Content |
|------|---------|
| `test/MT2/RT/interface/BandForge_Reading_MT2_P1_Interface_Data.json` | Reading P1 (13 Q) |
| `test/MT2/LT/interface/BandForge_Listening_MT2_S1_Interface_Data.json` | Listening S1 (10 Q, `form_completion`) |
| `test/MT1/RT/interface/BandForge_Reading_T2_Interface_Data.json` | MT1 reading passage 2 |

**Listening note:** Ingest supports `multiple_choice`, `matching`, `sentence_completion`, `form_completion`. `note_completion` / `map_labeling` are not ingested yet.

## CLI validate (optional)

```bash
cd backend && source .venv/bin/activate
python -c "
from scripts.normalize_reading_mock import flatten_questions
import json
data = json.load(open('seed/admin_samples/reading_mini.json'))
print(len(flatten_questions(data, part=1)), 'reading rows')
"
```
