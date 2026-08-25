-- Writing Skill Academic inventory: promote Mock 2 Writing + 3 Academic hubs
-- to reach 6 Task 1 + 6 Task 2 published practice hubs.
-- Does NOT activate writing_skill (separate step after PCI attach).
-- Idempotent via ON CONFLICT on deterministic UUIDs.

-- ---------------------------------------------------------------------------
-- MT2 Writing → practice_sets / hubs / bank content (from mock questions)
-- ---------------------------------------------------------------------------
INSERT INTO practice_sets (
  id, bank_id, set_number, title, difficulty, description, status, exam_module
)
VALUES
  (
    'c2000000-0000-4000-8000-000000000021',
    'a4b34ed4-ef87-4154-a18b-c6af5fdcd94e',
    6,
    'MT2_WT_T1',
    'medium',
    'Mock 2 writing task 1 (Academic).',
    'published',
    'academic'
  ),
  (
    'c2000000-0000-4000-8000-000000000022',
    'a4b34ed4-ef87-4154-a18b-c6af5fdcd94e',
    7,
    'MT2_WT_T2',
    'medium',
    'Mock 2 writing task 2 (Academic).',
    'published',
    'academic'
  )
ON CONFLICT (id) DO UPDATE SET
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  status = 'published',
  exam_module = 'academic';

INSERT INTO practice_hubs (
  id, set_id, slug, videos, practice_prompt, submit_config, estimated_min, sort_order
)
VALUES
  (
    'c2100000-0000-4000-8000-000000000021',
    'c2000000-0000-4000-8000-000000000021',
    'writing-mt2-t1',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"writing","href":"/practice/writing/c2100000-0000-4000-8000-000000000021/exercise"}'::jsonb,
    25,
    38
  ),
  (
    'c2100000-0000-4000-8000-000000000022',
    'c2000000-0000-4000-8000-000000000022',
    'writing-mt2-t2',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"writing","href":"/practice/writing/c2100000-0000-4000-8000-000000000022/exercise"}'::jsonb,
    40,
    39
  )
ON CONFLICT (id) DO UPDATE SET
  submit_config = EXCLUDED.submit_config,
  slug = EXCLUDED.slug;

INSERT INTO bank_sections (
  id, practice_set_id, module, part, title, passage_text, image_url
)
VALUES
  (
    'c2200000-0000-4000-8000-000000000021',
    'c2000000-0000-4000-8000-000000000021',
    'writing',
    1,
    'Writing Task 1',
    (SELECT prompt FROM questions WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000002' AND module = 'writing' AND part = 1 LIMIT 1),
    NULL
  ),
  (
    'c2200000-0000-4000-8000-000000000022',
    'c2000000-0000-4000-8000-000000000022',
    'writing',
    1,
    'Writing Task 2',
    (SELECT prompt FROM questions WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000002' AND module = 'writing' AND part = 2 LIMIT 1),
    NULL
  )
ON CONFLICT (id) DO UPDATE SET
  passage_text = EXCLUDED.passage_text,
  image_url = EXCLUDED.image_url;

DELETE FROM bank_questions
WHERE section_id IN (
  'c2200000-0000-4000-8000-000000000021',
  'c2200000-0000-4000-8000-000000000022'
);

INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, passage_text,
  options, correct_answer, skill_tag
)
SELECT
  CASE q.part
    WHEN 1 THEN 'c2200000-0000-4000-8000-000000000021'::uuid
    WHEN 2 THEN 'c2200000-0000-4000-8000-000000000022'::uuid
  END,
  1,
  q.question_type,
  q.prompt,
  q.prompt,
  coalesce(q.options, '{}'::jsonb),
  NULL,
  'writing'
FROM questions q
WHERE q.mock_test_id = 'a0000000-0000-4000-8000-000000000002'
  AND q.module = 'writing'
  AND q.part IN (1, 2);

-- ---------------------------------------------------------------------------
-- WS_AC_* hubs — prompts already authored in repo scripts/tests
-- ---------------------------------------------------------------------------
INSERT INTO practice_sets (
  id, bank_id, set_number, title, difficulty, description, status, exam_module
)
VALUES
  (
    'c6000000-0000-4000-8000-000000000021',
    'a4b34ed4-ef87-4154-a18b-c6af5fdcd94e',
    8,
    'WS_AC_T1_01',
    'medium',
    'Writing Skill Academic Task 1 — energy consumption table.',
    'published',
    'academic'
  ),
  (
    'c6000000-0000-4000-8000-000000000022',
    'a4b34ed4-ef87-4154-a18b-c6af5fdcd94e',
    9,
    'WS_AC_T2_01',
    'medium',
    'Writing Skill Academic Task 2 — technology and face-to-face communication.',
    'published',
    'academic'
  ),
  (
    'c6000000-0000-4000-8000-000000000023',
    'a4b34ed4-ef87-4154-a18b-c6af5fdcd94e',
    10,
    'WS_AC_T2_02',
    'medium',
    'Writing Skill Academic Task 2 — universities and practical skills.',
    'published',
    'academic'
  )
ON CONFLICT (id) DO UPDATE SET
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  status = 'published',
  exam_module = 'academic';

INSERT INTO practice_hubs (
  id, set_id, slug, videos, practice_prompt, submit_config, estimated_min, sort_order
)
VALUES
  (
    'c6100000-0000-4000-8000-000000000021',
    'c6000000-0000-4000-8000-000000000021',
    'writing-ws-ac-t1-01',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"writing","href":"/practice/writing/c6100000-0000-4000-8000-000000000021/exercise"}'::jsonb,
    25,
    40
  ),
  (
    'c6100000-0000-4000-8000-000000000022',
    'c6000000-0000-4000-8000-000000000022',
    'writing-ws-ac-t2-01',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"writing","href":"/practice/writing/c6100000-0000-4000-8000-000000000022/exercise"}'::jsonb,
    40,
    41
  ),
  (
    'c6100000-0000-4000-8000-000000000023',
    'c6000000-0000-4000-8000-000000000023',
    'writing-ws-ac-t2-02',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"writing","href":"/practice/writing/c6100000-0000-4000-8000-000000000023/exercise"}'::jsonb,
    40,
    42
  )
ON CONFLICT (id) DO UPDATE SET
  submit_config = EXCLUDED.submit_config,
  slug = EXCLUDED.slug;

INSERT INTO bank_sections (
  id, practice_set_id, module, part, title, passage_text, image_url
)
VALUES
  (
    'c6200000-0000-4000-8000-000000000021',
    'c6000000-0000-4000-8000-000000000021',
    'writing',
    1,
    'Writing Task 1',
    $prompt$You should spend about 20 minutes on this task.

The table below shows energy consumption by sector in four countries in 2020 (million tonnes of oil equivalent).

Summarise the information by selecting and reporting the main features, and make comparisons where relevant.

Write at least 150 words.$prompt$,
    NULL
  ),
  (
    'c6200000-0000-4000-8000-000000000022',
    'c6000000-0000-4000-8000-000000000022',
    'writing',
    1,
    'Writing Task 2',
    $prompt$You should spend about 40 minutes on this task.

Some people think that modern technology is making face-to-face communication less common and less important. Others believe that technology actually helps people stay connected in more meaningful ways.

Discuss both these views and give your own opinion.

Give reasons for your answer and include any relevant examples from your own knowledge or experience.

Write at least 250 words.$prompt$,
    NULL
  ),
  (
    'c6200000-0000-4000-8000-000000000023',
    'c6000000-0000-4000-8000-000000000023',
    'writing',
    1,
    'Writing Task 2',
    $prompt$You should spend about 40 minutes on this task.

Some people think universities should focus on practical skills that prepare students for work. Others believe that the main purpose of university education is to develop intellectual ability and critical thinking.

Discuss both these views and give your own opinion.

Give reasons for your answer and include any relevant examples from your own knowledge or experience.

Write at least 250 words.$prompt$,
    NULL
  )
ON CONFLICT (id) DO UPDATE SET
  passage_text = EXCLUDED.passage_text;

DELETE FROM bank_questions
WHERE section_id IN (
  'c6200000-0000-4000-8000-000000000021',
  'c6200000-0000-4000-8000-000000000022',
  'c6200000-0000-4000-8000-000000000023'
);

INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, passage_text,
  options, correct_answer, skill_tag
)
VALUES
  (
    'c6200000-0000-4000-8000-000000000021',
    1,
    'task1_academic',
    $prompt$You should spend about 20 minutes on this task.

The table below shows energy consumption by sector in four countries in 2020 (million tonnes of oil equivalent).

Summarise the information by selecting and reporting the main features, and make comparisons where relevant.

Write at least 150 words.$prompt$,
    $prompt$You should spend about 20 minutes on this task.

The table below shows energy consumption by sector in four countries in 2020 (million tonnes of oil equivalent).

Summarise the information by selecting and reporting the main features, and make comparisons where relevant.

Write at least 150 words.$prompt$,
    $opts${
      "min_words": 150,
      "title": "WRITING TASK 1 — Energy consumption by sector (2020)",
      "chart": {
        "type": "table",
        "title": "Energy consumption by sector, 2020 (Mtoe)",
        "source": "Illustrative energy statistics",
        "headers": ["Country", "Industry", "Transport", "Residential", "Other"],
        "rows": [
          ["Country A", 120, 85, 60, 25],
          ["Country B", 95, 110, 45, 30],
          ["Country C", 70, 55, 80, 20],
          ["Country D", 150, 90, 55, 40]
        ]
      }
    }$opts$::jsonb,
    NULL,
    'writing'
  ),
  (
    'c6200000-0000-4000-8000-000000000022',
    1,
    'task2',
    $prompt$You should spend about 40 minutes on this task.

Some people think that modern technology is making face-to-face communication less common and less important. Others believe that technology actually helps people stay connected in more meaningful ways.

Discuss both these views and give your own opinion.

Give reasons for your answer and include any relevant examples from your own knowledge or experience.

Write at least 250 words.$prompt$,
    $prompt$You should spend about 40 minutes on this task.

Some people think that modern technology is making face-to-face communication less common and less important. Others believe that technology actually helps people stay connected in more meaningful ways.

Discuss both these views and give your own opinion.

Give reasons for your answer and include any relevant examples from your own knowledge or experience.

Write at least 250 words.$prompt$,
    '{"min_words": 250}'::jsonb,
    NULL,
    'writing'
  ),
  (
    'c6200000-0000-4000-8000-000000000023',
    1,
    'task2',
    $prompt$You should spend about 40 minutes on this task.

Some people think universities should focus on practical skills that prepare students for work. Others believe that the main purpose of university education is to develop intellectual ability and critical thinking.

Discuss both these views and give your own opinion.

Give reasons for your answer and include any relevant examples from your own knowledge or experience.

Write at least 250 words.$prompt$,
    $prompt$You should spend about 40 minutes on this task.

Some people think universities should focus on practical skills that prepare students for work. Others believe that the main purpose of university education is to develop intellectual ability and critical thinking.

Discuss both these views and give your own opinion.

Give reasons for your answer and include any relevant examples from your own knowledge or experience.

Write at least 250 words.$prompt$,
    '{"min_words": 250}'::jsonb,
    NULL,
    'writing'
  );

-- ---------------------------------------------------------------------------
-- program_content_items (Academic track) + mock tagging
-- ---------------------------------------------------------------------------
UPDATE mock_tests
SET exam_module = 'academic'
WHERE id IN (
  'a0000000-0000-4000-8000-000000000001',
  'a0000000-0000-4000-8000-000000000002'
);

DELETE FROM program_content_items
WHERE plan_id = '53110749-2cc5-41d2-91b8-e7c1eddbe5b9';

INSERT INTO program_content_items (
  id, plan_id, item_type, item_id, exam_module, sort_order, is_active
)
VALUES
  ('d1000000-0000-4000-8000-000000000001', '53110749-2cc5-41d2-91b8-e7c1eddbe5b9', 'practice_hub', 'c1100000-0000-4000-8000-000000000021', 'academic', 1, true),
  ('d1000000-0000-4000-8000-000000000002', '53110749-2cc5-41d2-91b8-e7c1eddbe5b9', 'practice_hub', 'c1100000-0000-4000-8000-000000000022', 'academic', 2, true),
  ('d1000000-0000-4000-8000-000000000003', '53110749-2cc5-41d2-91b8-e7c1eddbe5b9', 'practice_hub', 'c2100000-0000-4000-8000-000000000021', 'academic', 3, true),
  ('d1000000-0000-4000-8000-000000000004', '53110749-2cc5-41d2-91b8-e7c1eddbe5b9', 'practice_hub', 'c2100000-0000-4000-8000-000000000022', 'academic', 4, true),
  ('d1000000-0000-4000-8000-000000000005', '53110749-2cc5-41d2-91b8-e7c1eddbe5b9', 'practice_hub', 'c3100000-0000-4000-8000-000000000021', 'academic', 5, true),
  ('d1000000-0000-4000-8000-000000000006', '53110749-2cc5-41d2-91b8-e7c1eddbe5b9', 'practice_hub', 'c3100000-0000-4000-8000-000000000022', 'academic', 6, true),
  ('d1000000-0000-4000-8000-000000000007', '53110749-2cc5-41d2-91b8-e7c1eddbe5b9', 'practice_hub', 'c4100000-0000-4000-8000-000000000021', 'academic', 7, true),
  ('d1000000-0000-4000-8000-000000000008', '53110749-2cc5-41d2-91b8-e7c1eddbe5b9', 'practice_hub', 'c4100000-0000-4000-8000-000000000022', 'academic', 8, true),
  ('d1000000-0000-4000-8000-000000000009', '53110749-2cc5-41d2-91b8-e7c1eddbe5b9', 'practice_hub', 'c5100000-0000-4000-8000-000000000021', 'academic', 9, true),
  ('d1000000-0000-4000-8000-00000000000a', '53110749-2cc5-41d2-91b8-e7c1eddbe5b9', 'practice_hub', 'c6100000-0000-4000-8000-000000000022', 'academic', 10, true),
  ('d1000000-0000-4000-8000-00000000000b', '53110749-2cc5-41d2-91b8-e7c1eddbe5b9', 'practice_hub', 'c6100000-0000-4000-8000-000000000021', 'academic', 11, true),
  ('d1000000-0000-4000-8000-00000000000c', '53110749-2cc5-41d2-91b8-e7c1eddbe5b9', 'practice_hub', 'c6100000-0000-4000-8000-000000000023', 'academic', 12, true),
  ('d1000000-0000-4000-8000-00000000000d', '53110749-2cc5-41d2-91b8-e7c1eddbe5b9', 'mock_test', 'a0000000-0000-4000-8000-000000000001', 'academic', 100, true);

-- Activate after inventory validators pass (12 Academic hubs + 1 mock).
UPDATE plans
SET is_active = true
WHERE slug = 'writing_skill';
