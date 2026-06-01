# Listening mock ingestion — founder JSON → Supabase

Canonical transform spec for BandForge founder listening assets in `test/listening/` (see `test/README.md`).
Normalizer: `backend/scripts/normalize_listening_mock.py`.

## Conventions (v1)

| Decision | Value |
|----------|--------|
| Greenfield mock UUID | `d0000000-0000-4000-8000-000000000001` |
| S2 mock UUID | `e0000000-0000-4000-8000-000000000002` |
| S3 mock UUID | `e0000000-0000-4000-8000-000000000003` |
| S4 mock UUID | `e0000000-0000-4000-8000-000000000004` |
| Isolated section mocks | DB `part = 1` (entire mock is one IELTS section) |
| Part audio | One R2 key per mock on all question rows |
| Transcript | Sidecar in `seed/generated/*.meta.json` only (no DB column) |

| Section | R2 audio key |
|---------|----------------|
| S2 | `listening/bandforge-s2/part-1/full.mp3` |
| S3 | `listening/bandforge-s3/part-1/full.mp3` |
| S4 | `listening/bandforge-s4/part-1/full.mp3` |

## Security (answers + audio)

- `correct_answer` is stored in Supabase but **never** returned by `GET /api/listening/{mock_id}/questions` (see `QUESTION_PUBLIC_COLUMNS`).
- Full transcripts live only in `seed/generated/*.meta.json` — not in the API.
- `audio_url` in DB is an **R2 object key**; the API returns a **presigned GET** only after `POST /api/listening/{mock_id}/start` (in-progress attempt required).
- R2 bucket must stay **private** (no public bucket policy). MP3s under `test/listening/audio/*.mp3` and `backend/audio_seed/**/full.mp3` are gitignored; upload via `upload_listening_audio` or `upload_m01_listening_audio` for M01.

## Founder JSON (S2)

| Field | Purpose |
|-------|---------|
| `question_groups[]` | MCQ 1–5 + matching 6–10 |
| `questions[].answer` | → `correct_answer` (single letter) |

Types: `multiple_choice` → `mcq`; `matching` → `matching`.

## Founder JSON (S4)

Note completion (10 gaps) → `sentence_completion` rows from `text_before` / `text_after`. Source: [`test/listening/interface/BandForge_Listening_S4_Interface_Data.json`](../../test/listening/interface/BandForge_Listening_S4_Interface_Data.json) (derived from `test/listening/transcripts/Listening_S4_Elevenlabs_Transcript.rtf`). Accepts alternate spellings via `accepted_answers` joined with `/` (e.g. `traveller/traveler`, `transit-oriented/transit oriented`).

## Founder JSON (S3)

| `question_type` | Ingestion |
|-----------------|-----------|
| `multiple_choice_multiple` | Flatten to **two `mcq` rows** (one mark per `question_numbers[]` entry; shared stem, instruction on first row only) |
| `multiple_choice_single` | → `mcq` |
| `sentence_completion` | → `sentence_completion` (`text_before` + `___` + `text_after`) |
| `map_labeling` / `note_completion` | Deferred |

Example: group `s3_mc_multi_1_2` with answers `["A","E"]` → Q1 correct `A`, Q2 correct `E`.

## CLI

**S2**

```bash
cp ../test/listening/audio/Listening_S2_Audio.mp3 audio_seed/bandforge-s2/part-1/full.mp3
python -m scripts.normalize_listening_mock \
  --input ../test/listening/interface/BandForge_Listening_S2_Interface_Data.json \
  --mock-id e0000000-0000-4000-8000-000000000002 \
  --audio-key listening/bandforge-s2/part-1/full.mp3 \
  --sql seed/bandforge_listening_s2_seed.sql
python -m scripts.upload_listening_audio --preset bandforge-s2
python -m scripts.verify_listening_mock --mock-id e0000000-0000-4000-8000-000000000002
```

**S3**

```bash
cp ../test/listening/audio/Listening_S3_Audio.mp3 audio_seed/bandforge-s3/part-1/full.mp3
python -m scripts.normalize_listening_mock \
  --input ../test/listening/interface/BandForge_Listening_S3_Interface_Data.json \
  --mock-id e0000000-0000-4000-8000-000000000003 \
  --audio-key listening/bandforge-s3/part-1/full.mp3 \
  --meta-out seed/generated/bandforge_s3.meta.json \
  --sql seed/bandforge_listening_s3_seed.sql
python -m scripts.upload_listening_audio --preset bandforge-s3
python -m scripts.verify_listening_mock --mock-id e0000000-0000-4000-8000-000000000003
```

**S4**

```bash
cp ../test/listening/audio/Listening_S4_Audio.mp3 audio_seed/bandforge-s4/part-1/full.mp3
python -m scripts.normalize_listening_mock \
  --input ../test/listening/interface/BandForge_Listening_S4_Interface_Data.json \
  --mock-id e0000000-0000-4000-8000-000000000004 \
  --audio-key listening/bandforge-s4/part-1/full.mp3 \
  --meta-out seed/generated/bandforge_s4.meta.json \
  --sql seed/bandforge_listening_s4_seed.sql
python -m scripts.upload_listening_audio --preset bandforge-s4
python -m scripts.verify_listening_mock --mock-id e0000000-0000-4000-8000-000000000004
```

Migrations: `20260525120000_bandforge_listening_s2.sql`, `20260525120100_bandforge_listening_s3.sql`, `20260525120200_bandforge_listening_s4.sql`.

## Frontend

| Hub part | URL | Mock UUID |
|----------|-----|-----------|
| 1 | `/test/listening?part=1` | Greenfield |
| 2 | `/test/listening?part=2` | S2 |
| 3 | `/test/listening?part=3` | S3 |
| 4 | `/test/listening?part=4` | S4 |

Renderers: `mcq`, `matching`, `sentence_completion` (text input), `form_completion` (Part 1 only).

## Smoke checklist

| Step | S2 | S3 | S4 |
|------|----|----|-----|
| DB seed | `verify_listening_mock` …0002 | …0003 | …0004 |
| R2 audio | `--preset bandforge-s2` | `bandforge-s3` | `bandforge-s4` |
| E2E | `?part=2` | `?part=3` | `?part=4` |
