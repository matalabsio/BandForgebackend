# Reading ingestion mapping

Founder content lives in `test/MT1/RT/interface/BandForge_Reading_T2_Interface_Data.json` and `test/MT1/RT/interface/BandForge_Reading_T3_Interface_Data.json`, sourced from `test/MT1/RT/source/Reading Task 2.pages` and `Reading Task 3.pages`.

## Stable mock IDs

| Hub passage | UUID | Title |
|-------------|------|-------|
| 1 | `b0000000-0000-4000-8000-000000000002` | The Hidden Forces Behind Everyday Choices |
| 2 | `b0000000-0000-4000-8000-000000000003` | When the Rainforests of the Sea Fall Silent |

Legacy Deferral mock `b0000000-...0001` is unpublished.

## Pipeline

```bash
cd backend && source .venv/bin/activate
python -m scripts.normalize_reading_mock \
  --input ../test/MT1/RT/interface/BandForge_Reading_T2_Interface_Data.json \
  --sql seed/bandforge_reading_t2_seed.sql
python -m scripts.apply_reading_seed ../test/MT1/RT/interface/BandForge_Reading_T2_Interface_Data.json
python -m scripts.verify_reading_mock --mock-id b0000000-0000-4000-8000-000000000002
```

## API (production UI)

- `POST /api/reading/{mock_test_id}/start`
- `GET /api/reading/{mock_test_id}/questions` (403 without in-progress attempt)
- `POST /api/reading/attempts/{attempt_id}/autosave`
- `POST /api/reading/attempts/{attempt_id}/submit`
- `GET /api/reading/attempts/{attempt_id}/score-report`

`correct_answer` is never returned in the questions response.

## Storage rules

- Full `passage_text` only on `question_number = 1`.
- `options` JSON for TFNG and matching headings only.

## Frontend routes

- Hub: `/test/reading`
- Exam: `/test/reading?passage=1|2`
- Results: `/test/reading/results/{attemptId}`
