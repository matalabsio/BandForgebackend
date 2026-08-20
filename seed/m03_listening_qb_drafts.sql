-- Draft Question Bank sets MT3_LT_S1–S4 from Mock 3 listening parts.
-- Status remains draft; do not publish.

INSERT INTO practice_sets (
  id, bank_id, set_number, title, difficulty, description, status
)
VALUES
  (
    'c3000000-0000-4000-8000-000000000001',
    '07923521-f6bc-4736-aca5-e39871bb8945',
    5,
    'MT3_LT_S1',
    'medium',
    'Mock 3 listening part 1 (draft).',
    'draft'
  ),
  (
    'c3000000-0000-4000-8000-000000000002',
    '07923521-f6bc-4736-aca5-e39871bb8945',
    6,
    'MT3_LT_S2',
    'medium',
    'Mock 3 listening part 2 (draft).',
    'draft'
  ),
  (
    'c3000000-0000-4000-8000-000000000003',
    '07923521-f6bc-4736-aca5-e39871bb8945',
    7,
    'MT3_LT_S3',
    'medium',
    'Mock 3 listening part 3 (draft).',
    'draft'
  ),
  (
    'c3000000-0000-4000-8000-000000000004',
    '07923521-f6bc-4736-aca5-e39871bb8945',
    8,
    'MT3_LT_S4',
    'medium',
    'Mock 3 listening part 4 (draft).',
    'draft'
  )
ON CONFLICT (id) DO UPDATE SET
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  status = 'draft';

INSERT INTO practice_hubs (
  id, set_id, slug, videos, practice_prompt, submit_config, estimated_min, sort_order
)
VALUES
  (
    'c3100000-0000-4000-8000-000000000001',
    'c3000000-0000-4000-8000-000000000001',
    'listening-mt3-s1',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"listening","href":"/practice/listening/c3100000-0000-4000-8000-000000000001/exercise"}'::jsonb,
    25,
    13
  ),
  (
    'c3100000-0000-4000-8000-000000000002',
    'c3000000-0000-4000-8000-000000000002',
    'listening-mt3-s2',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"listening","href":"/practice/listening/c3100000-0000-4000-8000-000000000002/exercise"}'::jsonb,
    25,
    14
  ),
  (
    'c3100000-0000-4000-8000-000000000003',
    'c3000000-0000-4000-8000-000000000003',
    'listening-mt3-s3',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"listening","href":"/practice/listening/c3100000-0000-4000-8000-000000000003/exercise"}'::jsonb,
    25,
    15
  ),
  (
    'c3100000-0000-4000-8000-000000000004',
    'c3000000-0000-4000-8000-000000000004',
    'listening-mt3-s4',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"listening","href":"/practice/listening/c3100000-0000-4000-8000-000000000004/exercise"}'::jsonb,
    25,
    16
  )
ON CONFLICT (id) DO UPDATE SET
  submit_config = EXCLUDED.submit_config;

INSERT INTO bank_sections (
  id, practice_set_id, module, part, title, audio_key
)
VALUES
  (
    'c3200000-0000-4000-8000-000000000001',
    'c3000000-0000-4000-8000-000000000001',
    'listening',
    1,
    'MT3_LT_S1',
    'bank/c3000000-0000-4000-8000-000000000001/listening/part1/audio.mp3'
  ),
  (
    'c3200000-0000-4000-8000-000000000002',
    'c3000000-0000-4000-8000-000000000002',
    'listening',
    1,
    'MT3_LT_S2',
    'bank/c3000000-0000-4000-8000-000000000002/listening/part1/audio.mp3'
  ),
  (
    'c3200000-0000-4000-8000-000000000003',
    'c3000000-0000-4000-8000-000000000003',
    'listening',
    1,
    'MT3_LT_S3',
    'bank/c3000000-0000-4000-8000-000000000003/listening/part1/audio.mp3'
  ),
  (
    'c3200000-0000-4000-8000-000000000004',
    'c3000000-0000-4000-8000-000000000004',
    'listening',
    1,
    'MT3_LT_S4',
    'bank/c3000000-0000-4000-8000-000000000004/listening/part1/audio.mp3'
  )
ON CONFLICT (id) DO UPDATE SET
  audio_key = EXCLUDED.audio_key,
  title = EXCLUDED.title;

DELETE FROM bank_questions
WHERE section_id IN (
  'c3200000-0000-4000-8000-000000000001',
  'c3200000-0000-4000-8000-000000000002',
  'c3200000-0000-4000-8000-000000000003',
  'c3200000-0000-4000-8000-000000000004'
);

INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, passage_text,
  audio_url, options, correct_answer, skill_tag
)
SELECT
  CASE q.part
    WHEN 1 THEN 'c3200000-0000-4000-8000-000000000001'::uuid
    WHEN 2 THEN 'c3200000-0000-4000-8000-000000000002'::uuid
    WHEN 3 THEN 'c3200000-0000-4000-8000-000000000003'::uuid
    WHEN 4 THEN 'c3200000-0000-4000-8000-000000000004'::uuid
  END,
  q.question_number,
  q.question_type,
  q.prompt,
  q.passage_text,
  CASE q.part
    WHEN 1 THEN 'bank/c3000000-0000-4000-8000-000000000001/listening/part1/audio.mp3'
    WHEN 2 THEN 'bank/c3000000-0000-4000-8000-000000000002/listening/part1/audio.mp3'
    WHEN 3 THEN 'bank/c3000000-0000-4000-8000-000000000003/listening/part1/audio.mp3'
    WHEN 4 THEN 'bank/c3000000-0000-4000-8000-000000000004/listening/part1/audio.mp3'
  END,
  q.options,
  q.correct_answer,
  q.skill_tag
FROM questions q
WHERE q.mock_test_id = 'a0000000-0000-4000-8000-000000000003'
  AND q.module = 'listening'
  AND q.part BETWEEN 1 AND 4;
