-- Draft Question Bank sets MT1_RT_S1–S2 + MT1_WT_T1–T2 from Mock 1 reading/writing only.
-- Excludes BandForge Free Diagnostic (d0000000-0000-4000-8000-000000000001).
-- Status remains draft; do not publish.

INSERT INTO practice_sets (
  id, bank_id, set_number, title, difficulty, description, status
)
VALUES
  (
    'c1000000-0000-4000-8000-000000000011',
    '53e900cd-b0c9-4666-9f6b-66a2c6ba46bd',
    13,
    'MT1_RT_S1',
    'medium',
    'Mock 1 reading passage 1 (draft).',
    'draft'
  ),
  (
    'c1000000-0000-4000-8000-000000000012',
    '53e900cd-b0c9-4666-9f6b-66a2c6ba46bd',
    14,
    'MT1_RT_S2',
    'medium',
    'Mock 1 reading passage 2 (draft).',
    'draft'
  ),
  (
    'c1000000-0000-4000-8000-000000000021',
    'a4b34ed4-ef87-4154-a18b-c6af5fdcd94e',
    6,
    'MT1_WT_T1',
    'medium',
    'Mock 1 writing task 1 (draft).',
    'draft'
  ),
  (
    'c1000000-0000-4000-8000-000000000022',
    'a4b34ed4-ef87-4154-a18b-c6af5fdcd94e',
    7,
    'MT1_WT_T2',
    'medium',
    'Mock 1 writing task 2 (draft).',
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
    'c1100000-0000-4000-8000-000000000011',
    'c1000000-0000-4000-8000-000000000011',
    'reading-mt1-s1',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"reading","href":"/practice/reading/c1100000-0000-4000-8000-000000000011/exercise"}'::jsonb,
    20,
    31
  ),
  (
    'c1100000-0000-4000-8000-000000000012',
    'c1000000-0000-4000-8000-000000000012',
    'reading-mt1-s2',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"reading","href":"/practice/reading/c1100000-0000-4000-8000-000000000012/exercise"}'::jsonb,
    20,
    32
  ),
  (
    'c1100000-0000-4000-8000-000000000021',
    'c1000000-0000-4000-8000-000000000021',
    'writing-mt1-t1',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"writing","href":"/practice/writing/c1100000-0000-4000-8000-000000000021/exercise"}'::jsonb,
    25,
    33
  ),
  (
    'c1100000-0000-4000-8000-000000000022',
    'c1000000-0000-4000-8000-000000000022',
    'writing-mt1-t2',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"writing","href":"/practice/writing/c1100000-0000-4000-8000-000000000022/exercise"}'::jsonb,
    40,
    34
  )
ON CONFLICT (id) DO UPDATE SET
  submit_config = EXCLUDED.submit_config;

INSERT INTO bank_sections (
  id, practice_set_id, module, part, title, passage_text, image_url
)
VALUES
  (
    'c1200000-0000-4000-8000-000000000011',
    'c1000000-0000-4000-8000-000000000011',
    'reading',
    1,
    'MT1_RT_S1',
    (SELECT passage_text FROM questions WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001' AND module = 'reading' AND part = 1 AND question_number = 1 LIMIT 1),
    NULL
  ),
  (
    'c1200000-0000-4000-8000-000000000012',
    'c1000000-0000-4000-8000-000000000012',
    'reading',
    1,
    'MT1_RT_S2',
    (SELECT passage_text FROM questions WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001' AND module = 'reading' AND part = 2 AND question_number = 1 LIMIT 1),
    NULL
  ),
  (
    'c1200000-0000-4000-8000-000000000021',
    'c1000000-0000-4000-8000-000000000021',
    'writing',
    1,
    'MT1_WT_T1',
    (SELECT prompt FROM questions WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001' AND module = 'writing' AND part = 1 LIMIT 1),
    NULL
  ),
  (
    'c1200000-0000-4000-8000-000000000022',
    'c1000000-0000-4000-8000-000000000022',
    'writing',
    1,
    'MT1_WT_T2',
    (SELECT prompt FROM questions WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001' AND module = 'writing' AND part = 2 LIMIT 1),
    NULL
  )
ON CONFLICT (id) DO UPDATE SET
  title = EXCLUDED.title,
  passage_text = EXCLUDED.passage_text,
  image_url = EXCLUDED.image_url;

DELETE FROM bank_questions
WHERE section_id IN (
  'c1200000-0000-4000-8000-000000000011',
  'c1200000-0000-4000-8000-000000000012',
  'c1200000-0000-4000-8000-000000000021',
  'c1200000-0000-4000-8000-000000000022'
);

INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, passage_text,
  options, correct_answer, skill_tag
)
SELECT
  CASE q.part
    WHEN 1 THEN 'c1200000-0000-4000-8000-000000000011'::uuid
    WHEN 2 THEN 'c1200000-0000-4000-8000-000000000012'::uuid
  END,
  q.question_number,
  q.question_type,
  q.prompt,
  q.passage_text,
  q.options,
  q.correct_answer,
  q.skill_tag
FROM questions q
WHERE q.mock_test_id = 'a0000000-0000-4000-8000-000000000001'
  AND q.module = 'reading'
  AND q.part IN (1, 2);

INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, passage_text,
  options, correct_answer, skill_tag
)
SELECT
  CASE q.part
    WHEN 1 THEN 'c1200000-0000-4000-8000-000000000021'::uuid
    WHEN 2 THEN 'c1200000-0000-4000-8000-000000000022'::uuid
  END,
  1,
  q.question_type,
  q.prompt,
  q.prompt,
  q.options,
  q.correct_answer,
  q.question_type
FROM questions q
WHERE q.mock_test_id = 'a0000000-0000-4000-8000-000000000001'
  AND q.module = 'writing'
  AND q.part IN (1, 2);
