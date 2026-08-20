-- Draft Question Bank sets MT1_ST_P1–P3 from Mock 1 speaking parts only.
-- Speaking Bank 4 (official catalogue). Excludes diagnostic mock.
-- Status remains draft; do not publish.

INSERT INTO practice_sets (
  id, bank_id, set_number, title, difficulty, description, status
)
VALUES
  (
    'c1000000-0000-4000-8000-000000000031',
    'fa62779b-148c-401d-b66d-5a7e4fbba6fc',
    1,
    'MT1_ST_P1',
    'medium',
    'Mock 1 speaking part 1 (draft).',
    'draft'
  ),
  (
    'c1000000-0000-4000-8000-000000000032',
    'fa62779b-148c-401d-b66d-5a7e4fbba6fc',
    2,
    'MT1_ST_P2',
    'medium',
    'Mock 1 speaking part 2 (draft).',
    'draft'
  ),
  (
    'c1000000-0000-4000-8000-000000000033',
    'fa62779b-148c-401d-b66d-5a7e4fbba6fc',
    3,
    'MT1_ST_P3',
    'medium',
    'Mock 1 speaking part 3 (draft).',
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
    'c1100000-0000-4000-8000-000000000031',
    'c1000000-0000-4000-8000-000000000031',
    'speaking-mt1-p1',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"speaking","href":"/practice/speaking/c1100000-0000-4000-8000-000000000031/exercise"}'::jsonb,
    15,
    35
  ),
  (
    'c1100000-0000-4000-8000-000000000032',
    'c1000000-0000-4000-8000-000000000032',
    'speaking-mt1-p2',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"speaking","href":"/practice/speaking/c1100000-0000-4000-8000-000000000032/exercise"}'::jsonb,
    15,
    36
  ),
  (
    'c1100000-0000-4000-8000-000000000033',
    'c1000000-0000-4000-8000-000000000033',
    'speaking-mt1-p3',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"speaking","href":"/practice/speaking/c1100000-0000-4000-8000-000000000033/exercise"}'::jsonb,
    15,
    37
  )
ON CONFLICT (id) DO UPDATE SET
  submit_config = EXCLUDED.submit_config;

INSERT INTO bank_sections (
  id, practice_set_id, module, part, title
)
VALUES
  (
    'c1200000-0000-4000-8000-000000000031',
    'c1000000-0000-4000-8000-000000000031',
    'speaking',
    1,
    'MT1_ST_P1'
  ),
  (
    'c1200000-0000-4000-8000-000000000032',
    'c1000000-0000-4000-8000-000000000032',
    'speaking',
    1,
    'MT1_ST_P2'
  ),
  (
    'c1200000-0000-4000-8000-000000000033',
    'c1000000-0000-4000-8000-000000000033',
    'speaking',
    1,
    'MT1_ST_P3'
  )
ON CONFLICT (id) DO UPDATE SET
  title = EXCLUDED.title;

DELETE FROM bank_questions
WHERE section_id IN (
  'c1200000-0000-4000-8000-000000000031',
  'c1200000-0000-4000-8000-000000000032',
  'c1200000-0000-4000-8000-000000000033'
);

INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, options, correct_answer, skill_tag
)
SELECT
  CASE q.part
    WHEN 1 THEN 'c1200000-0000-4000-8000-000000000031'::uuid
    WHEN 2 THEN 'c1200000-0000-4000-8000-000000000032'::uuid
    WHEN 3 THEN 'c1200000-0000-4000-8000-000000000033'::uuid
  END,
  q.question_number,
  q.question_type,
  q.prompt,
  CASE
    WHEN q.part = 1 THEN
      jsonb_build_object(
        'kind', 'question',
        'part_label', 'Part 1',
        'speak_time_sec', 30,
        'min_skip_sec', 5,
        'prep_sec', 0,
        'record_sec', 120,
        'video_url', NULL
      )
    WHEN q.part = 2 THEN
      jsonb_build_object(
        'kind', 'part2_intro',
        'part_label', 'Part 2',
        'speak_time_sec', 120,
        'min_skip_sec', 30,
        'prep_sec', 60,
        'record_sec', 120,
        'video_url', NULL
      )
    ELSE
      jsonb_build_object(
        'kind', 'question',
        'part_label', 'Part 3',
        'speak_time_sec', 45,
        'min_skip_sec', 5,
        'prep_sec', 0,
        'record_sec', 60,
        'video_url', NULL
      )
  END,
  '',
  'speaking'
FROM questions q
WHERE q.mock_test_id = 'a0000000-0000-4000-8000-000000000001'
  AND q.module = 'speaking'
  AND q.part BETWEEN 1 AND 3;
