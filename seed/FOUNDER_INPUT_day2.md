# Founder input — Day 2 test engine (Postman / seed data)

Fill in the sections below, then run the SQL seed (or your own inserts) in Supabase SQL Editor.

---

## 1. mock_test_id

```
<!-- PASTE_UUID: published mock test -->
```

Example after seed: copy from `SELECT id, title FROM mock_tests WHERE is_published = true;`

---

## 2. Reading sample (min 3–5 questions)

Store `correct_answer` in the database only — never exposed by the API.

```json
<!-- PASTE: JSON array of questions, or use seed/day2_dev_seed.sql -->
```

---

## 3. Listening sample (min 3–5 questions)

`questions.audio_url` must be the **R2 object key** (not a public URL), e.g.:

```
listening/YOUR_MOCK_ID/section-1.mp3
```

---

## 4. R2 uploads

Upload MP3 files to bucket `bandforge-speaking-audio` (or your `R2_BUCKET_NAME`):

```
<!-- LIST keys you uploaded, e.g.
listening/demo-mock/section-1.mp3
-->
```

---

## 5. Optional decisions

| Decision | Your choice | Default used in code |
|----------|-------------|----------------------|
| Unpublished tests in dev | | Visible when `APP_ENV=development` |
| Block duplicate in-progress attempt | | Yes |
| `audio_url` format in DB | | R2 object key |

---

## Postman flow

1. `POST {{base_url}}/auth/login` → set `access_token`
2. `POST {{base_url}}/api/tests/{{mock_test_id}}/start` body `{ "module": "reading" }` → set `attempt_id`
3. `GET {{base_url}}/api/tests/{{mock_test_id}}/questions?module=reading`
4. `POST {{base_url}}/api/attempts/{{attempt_id}}/submit` with answers array

Confirm: no `correct_answer` in any response.
