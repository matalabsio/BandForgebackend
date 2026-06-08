# Full mock ingestion (M01, M02, …)

## Drive layout (founder handoff)

```text
M01_Full_Academic_Mock/
  manifest.json
  01_Listening/S01/ M01_LIS_S01_Recording.mp3 …
  02_Reading/P01/ …
```

## Repo layout

```text
test/MT1/                         # Mock Test 1 (m01)
  manifest.json
  LT/  audio/ interface/ transcripts/ source/ screenshots/
  RT/  interface/ source/
  WT/  WRITING TASK *.pdf
test/MT2/                         # Mock Test 2 (m02)
  manifest.json
  LT/  audio/ interface/ pdf/ transcripts/
  RT/  interface/ source/
  WT/  WT Task *.docx
```

Paths are centralized in `backend/scripts/test_content_paths.py`.

## manifest.json

```json
{
  "id": "a0000000-0000-4000-8000-000000000001",
  "title": "IELTS Academic Mock 1",
  "description": "Full academic mock",
  "modules": [
    { "module": "reading", "sequence_order": 1, "duration_minutes": 60, "is_enabled": true },
    { "module": "listening", "sequence_order": 2, "duration_minutes": 30, "is_enabled": true },
    { "module": "writing", "sequence_order": 3, "duration_minutes": 60, "is_enabled": false },
    { "module": "speaking", "sequence_order": 4, "duration_minutes": 14, "is_enabled": false }
  ]
}
```

## CLI

```bash
cd backend && source .venv/bin/activate
python -m scripts.import_mock --mock-dir ../test/MT1 --dry-run
```

Apply DB: run migrations `20260526100000_mock_attempts_orchestration.sql`, `20260526100100_m01_consolidation.sql`, `20260526100200_test_attempts_part.sql`.

Audio:

```bash
# M01: upload from test/MT1/LT/audio/ (keys test/Listening_S*_Audio.mp3 in R2)
python -m scripts.upload_m01_listening_audio --dry-run
python -m scripts.upload_m01_listening_audio
```

## Orchestration

- One `mock_tests` row per full exam
- `questions.part` = listening part (1–4) or reading passage (1–3)
- `mock_attempts` groups module `test_attempts`
- Sequential unlock via `mock_test_modules.sequence_order`

## Adding Mock 2 / Mock 3

1. Insert `mock_tests` + `mock_test_modules` rows (or extend `manifest.json` and run `import_mock`).
2. Import questions with the new `mock_test_id`, `module`, and `part` (never separate mock IDs per section).
3. Add the UUID to `PUBLISHED_FULL_MOCK_IDS` in `backend/app/mock_catalog/constants.py`.
4. Add a slug entry in `frontend/lib/mock-catalog.ts` (`MOCK_SLUGS`).
5. No new frontend route structure: `/mock/[mockSlug]` and `useMockSession` work for any published mock.
