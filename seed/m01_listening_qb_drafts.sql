-- Draft Question Bank sets MT1_LT_S1–S4 from Mock 1 listening parts only.
-- Listening Bank 4 (official catalogue). Excludes diagnostic mock.
-- Status remains draft; do not publish.

INSERT INTO practice_sets (
  id, bank_id, set_number, title, difficulty, description, status
)
VALUES
  (
    'c1000000-0000-4000-8000-000000000001',
    '56c3b368-b7d1-4386-9d05-b344c22157be',
    1,
    'MT1_LT_S1',
    'medium',
    'Mock 1 listening part 1 (draft).',
    'draft'
  ),
  (
    'c1000000-0000-4000-8000-000000000002',
    '56c3b368-b7d1-4386-9d05-b344c22157be',
    2,
    'MT1_LT_S2',
    'medium',
    'Mock 1 listening part 2 (draft).',
    'draft'
  ),
  (
    'c1000000-0000-4000-8000-000000000003',
    '56c3b368-b7d1-4386-9d05-b344c22157be',
    3,
    'MT1_LT_S3',
    'medium',
    'Mock 1 listening part 3 (draft).',
    'draft'
  ),
  (
    'c1000000-0000-4000-8000-000000000004',
    '56c3b368-b7d1-4386-9d05-b344c22157be',
    4,
    'MT1_LT_S4',
    'medium',
    'Mock 1 listening part 4 (draft).',
    'draft'
  )
ON CONFLICT (id) DO UPDATE SET
  bank_id = EXCLUDED.bank_id,
  set_number = EXCLUDED.set_number,
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  status = 'draft';

INSERT INTO practice_hubs (
  id, set_id, slug, videos, practice_prompt, submit_config, estimated_min, sort_order
)
VALUES
  (
    'c1100000-0000-4000-8000-000000000001',
    'c1000000-0000-4000-8000-000000000001',
    'listening-mt1-s1',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"listening","href":"/practice/listening/c1100000-0000-4000-8000-000000000001/exercise"}'::jsonb,
    25,
    27
  ),
  (
    'c1100000-0000-4000-8000-000000000002',
    'c1000000-0000-4000-8000-000000000002',
    'listening-mt1-s2',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"listening","href":"/practice/listening/c1100000-0000-4000-8000-000000000002/exercise"}'::jsonb,
    25,
    28
  ),
  (
    'c1100000-0000-4000-8000-000000000003',
    'c1000000-0000-4000-8000-000000000003',
    'listening-mt1-s3',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"listening","href":"/practice/listening/c1100000-0000-4000-8000-000000000003/exercise"}'::jsonb,
    25,
    29
  ),
  (
    'c1100000-0000-4000-8000-000000000004',
    'c1000000-0000-4000-8000-000000000004',
    'listening-mt1-s4',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"listening","href":"/practice/listening/c1100000-0000-4000-8000-000000000004/exercise"}'::jsonb,
    25,
    30
  )
ON CONFLICT (id) DO UPDATE SET
  submit_config = EXCLUDED.submit_config;

INSERT INTO bank_sections (
  id, practice_set_id, module, part, title, audio_key
)
VALUES
  (
    'c1200000-0000-4000-8000-000000000001',
    'c1000000-0000-4000-8000-000000000001',
    'listening',
    1,
    'MT1_LT_S1',
    'bank/c1000000-0000-4000-8000-000000000001/listening/part1/audio.mp3'
  ),
  (
    'c1200000-0000-4000-8000-000000000002',
    'c1000000-0000-4000-8000-000000000002',
    'listening',
    1,
    'MT1_LT_S2',
    'bank/c1000000-0000-4000-8000-000000000002/listening/part1/audio.mp3'
  ),
  (
    'c1200000-0000-4000-8000-000000000003',
    'c1000000-0000-4000-8000-000000000003',
    'listening',
    1,
    'MT1_LT_S3',
    'bank/c1000000-0000-4000-8000-000000000003/listening/part1/audio.mp3'
  ),
  (
    'c1200000-0000-4000-8000-000000000004',
    'c1000000-0000-4000-8000-000000000004',
    'listening',
    1,
    'MT1_LT_S4',
    'bank/c1000000-0000-4000-8000-000000000004/listening/part1/audio.mp3'
  )
ON CONFLICT (id) DO UPDATE SET
  audio_key = EXCLUDED.audio_key,
  title = EXCLUDED.title;

DELETE FROM bank_questions
WHERE section_id IN (
  'c1200000-0000-4000-8000-000000000001',
  'c1200000-0000-4000-8000-000000000002',
  'c1200000-0000-4000-8000-000000000003',
  'c1200000-0000-4000-8000-000000000004'
);

INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, passage_text,
  audio_url, options, correct_answer, skill_tag
)
SELECT
  CASE q.part
    WHEN 1 THEN 'c1200000-0000-4000-8000-000000000001'::uuid
    WHEN 2 THEN 'c1200000-0000-4000-8000-000000000002'::uuid
    WHEN 3 THEN 'c1200000-0000-4000-8000-000000000003'::uuid
    WHEN 4 THEN 'c1200000-0000-4000-8000-000000000004'::uuid
  END,
  q.question_number,
  q.question_type,
  q.prompt,
  q.passage_text,
  CASE q.part
    WHEN 1 THEN 'bank/c1000000-0000-4000-8000-000000000001/listening/part1/audio.mp3'
    WHEN 2 THEN 'bank/c1000000-0000-4000-8000-000000000002/listening/part1/audio.mp3'
    WHEN 3 THEN 'bank/c1000000-0000-4000-8000-000000000003/listening/part1/audio.mp3'
    WHEN 4 THEN 'bank/c1000000-0000-4000-8000-000000000004/listening/part1/audio.mp3'
  END,
  q.options,
  q.correct_answer,
  q.skill_tag
FROM questions q
WHERE q.mock_test_id = 'a0000000-0000-4000-8000-000000000001'
  AND q.module = 'listening'
  AND q.part BETWEEN 1 AND 4;
