-- Draft Question Bank sets MT4_RT_S1–S3 + MT4_WT_T1–T2 from Mock 4 reading/writing.
-- Status remains draft; do not publish.

INSERT INTO practice_sets (
  id, bank_id, set_number, title, difficulty, description, status
)
VALUES
  (
    'c4000000-0000-4000-8000-000000000011',
    '53e900cd-b0c9-4666-9f6b-66a2c6ba46bd',
    7,
    'MT4_RT_S1',
    'medium',
    'Mock 4 reading passage 1 (draft).',
    'draft'
  ),
  (
    'c4000000-0000-4000-8000-000000000012',
    '53e900cd-b0c9-4666-9f6b-66a2c6ba46bd',
    8,
    'MT4_RT_S2',
    'medium',
    'Mock 4 reading passage 2 (draft).',
    'draft'
  ),
  (
    'c4000000-0000-4000-8000-000000000013',
    '53e900cd-b0c9-4666-9f6b-66a2c6ba46bd',
    9,
    'MT4_RT_S3',
    'medium',
    'Mock 4 reading passage 3 (draft).',
    'draft'
  ),
  (
    'c4000000-0000-4000-8000-000000000021',
    'a4b34ed4-ef87-4154-a18b-c6af5fdcd94e',
    3,
    'MT4_WT_T1',
    'medium',
    'Mock 4 writing task 1 (draft).',
    'draft'
  ),
  (
    'c4000000-0000-4000-8000-000000000022',
    'a4b34ed4-ef87-4154-a18b-c6af5fdcd94e',
    4,
    'MT4_WT_T2',
    'medium',
    'Mock 4 writing task 2 (draft).',
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
    'c4100000-0000-4000-8000-000000000011',
    'c4000000-0000-4000-8000-000000000011',
    'reading-mt4-s1',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"reading","href":"/practice/reading/c4100000-0000-4000-8000-000000000011/exercise"}'::jsonb,
    20,
    22
  ),
  (
    'c4100000-0000-4000-8000-000000000012',
    'c4000000-0000-4000-8000-000000000012',
    'reading-mt4-s2',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"reading","href":"/practice/reading/c4100000-0000-4000-8000-000000000012/exercise"}'::jsonb,
    20,
    23
  ),
  (
    'c4100000-0000-4000-8000-000000000013',
    'c4000000-0000-4000-8000-000000000013',
    'reading-mt4-s3',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"reading","href":"/practice/reading/c4100000-0000-4000-8000-000000000013/exercise"}'::jsonb,
    20,
    24
  ),
  (
    'c4100000-0000-4000-8000-000000000021',
    'c4000000-0000-4000-8000-000000000021',
    'writing-mt4-t1',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"writing","href":"/practice/writing/c4100000-0000-4000-8000-000000000021/exercise"}'::jsonb,
    25,
    25
  ),
  (
    'c4100000-0000-4000-8000-000000000022',
    'c4000000-0000-4000-8000-000000000022',
    'writing-mt4-t2',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"writing","href":"/practice/writing/c4100000-0000-4000-8000-000000000022/exercise"}'::jsonb,
    40,
    26
  )
ON CONFLICT (id) DO UPDATE SET
  submit_config = EXCLUDED.submit_config;

INSERT INTO bank_sections (
  id, practice_set_id, module, part, title, passage_text, image_url
)
VALUES
  (
    'c4200000-0000-4000-8000-000000000011',
    'c4000000-0000-4000-8000-000000000011',
    'reading',
    1,
    'MT4_RT_S1',
    (SELECT passage_text FROM questions WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000004' AND module = 'reading' AND part = 1 AND question_number = 1 LIMIT 1),
    NULL
  ),
  (
    'c4200000-0000-4000-8000-000000000012',
    'c4000000-0000-4000-8000-000000000012',
    'reading',
    1,
    'MT4_RT_S2',
    (SELECT passage_text FROM questions WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000004' AND module = 'reading' AND part = 2 AND question_number = 14 LIMIT 1),
    NULL
  ),
  (
    'c4200000-0000-4000-8000-000000000013',
    'c4000000-0000-4000-8000-000000000013',
    'reading',
    1,
    'MT4_RT_S3',
    (SELECT passage_text FROM questions WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000004' AND module = 'reading' AND part = 3 AND question_number = 27 LIMIT 1),
    NULL
  ),
  (
    'c4200000-0000-4000-8000-000000000021',
    'c4000000-0000-4000-8000-000000000021',
    'writing',
    1,
    'MT4_WT_T1',
    (SELECT prompt FROM questions WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000004' AND module = 'writing' AND part = 1 LIMIT 1),
    'bank/c4000000-0000-4000-8000-000000000021/writing/part1/chart.png'
  ),
  (
    'c4200000-0000-4000-8000-000000000022',
    'c4000000-0000-4000-8000-000000000022',
    'writing',
    1,
    'MT4_WT_T2',
    (SELECT prompt FROM questions WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000004' AND module = 'writing' AND part = 2 LIMIT 1),
    NULL
  )
ON CONFLICT (id) DO UPDATE SET
  title = EXCLUDED.title,
  passage_text = EXCLUDED.passage_text,
  image_url = EXCLUDED.image_url;

DELETE FROM bank_questions
WHERE section_id IN (
  'c4200000-0000-4000-8000-000000000011',
  'c4200000-0000-4000-8000-000000000012',
  'c4200000-0000-4000-8000-000000000013',
  'c4200000-0000-4000-8000-000000000021',
  'c4200000-0000-4000-8000-000000000022'
);

INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, passage_text,
  options, correct_answer, skill_tag
)
SELECT
  CASE q.part
    WHEN 1 THEN 'c4200000-0000-4000-8000-000000000011'::uuid
    WHEN 2 THEN 'c4200000-0000-4000-8000-000000000012'::uuid
    WHEN 3 THEN 'c4200000-0000-4000-8000-000000000013'::uuid
  END,
  q.question_number,
  q.question_type,
  q.prompt,
  q.passage_text,
  q.options,
  q.correct_answer,
  q.skill_tag
FROM questions q
WHERE q.mock_test_id = 'a0000000-0000-4000-8000-000000000004'
  AND q.module = 'reading'
  AND q.part BETWEEN 1 AND 3;

INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, passage_text,
  options, correct_answer, skill_tag
)
SELECT
  CASE q.part
    WHEN 1 THEN 'c4200000-0000-4000-8000-000000000021'::uuid
    WHEN 2 THEN 'c4200000-0000-4000-8000-000000000022'::uuid
  END,
  1,
  q.question_type,
  q.prompt,
  q.prompt,
  CASE
    WHEN q.part = 1 THEN
      jsonb_set(
        COALESCE(q.options, '{}'::jsonb),
        '{image_url}',
        '"bank/c4000000-0000-4000-8000-000000000021/writing/part1/chart.png"'::jsonb
      )
    ELSE q.options
  END,
  q.correct_answer,
  q.question_type
FROM questions q
WHERE q.mock_test_id = 'a0000000-0000-4000-8000-000000000004'
  AND q.module = 'writing'
  AND q.part IN (1, 2);
