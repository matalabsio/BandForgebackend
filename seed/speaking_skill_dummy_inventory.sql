-- Speaking Skill dummy inventory: 9 published part hubs cloned from live MT1 templates.
-- Produces SS_P1_02..04, SS_P2_02..04, SS_P3_02..04 (with existing MT1 → 4+4+4).
--
-- Does NOT activate speaking_skill.
-- Does NOT insert program_content_items.
-- Does NOT UPDATE existing MT1 sets/hubs/questions (ensure uses ON CONFLICT DO NOTHING).
-- Idempotent via deterministic UUIDs + ON CONFLICT.

-- ---------------------------------------------------------------------------
-- 0) Ensure live Speaking Bank 4 UUID exists (local DBs may use a different id)
-- ---------------------------------------------------------------------------
INSERT INTO practice_banks (id, skill, bank_number, title, weakness_tags)
SELECT
  'fa62779b-148c-401d-b66d-5a7e4fbba6fc'::uuid,
  'speaking',
  COALESCE(
    (
      SELECT MAX(bank_number) + 1
      FROM practice_banks
      WHERE skill = 'speaking'
    ),
    4
  )::smallint,
  'Speaking Bank 4',
  ARRAY['speaking_bank_4']::text[]
WHERE NOT EXISTS (
  SELECT 1
  FROM practice_banks
  WHERE id = 'fa62779b-148c-401d-b66d-5a7e4fbba6fc'
);

-- ---------------------------------------------------------------------------
-- 1) Ensure MT1 part templates exist (insert-only; never modify existing rows)
--    Content matches live MT1 / M01 speaking prompts + options.
-- ---------------------------------------------------------------------------
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
    'published'
  ),
  (
    'c1000000-0000-4000-8000-000000000032',
    'fa62779b-148c-401d-b66d-5a7e4fbba6fc',
    2,
    'MT1_ST_P2',
    'medium',
    'Mock 1 speaking part 2 (draft).',
    'published'
  ),
  (
    'c1000000-0000-4000-8000-000000000033',
    'fa62779b-148c-401d-b66d-5a7e4fbba6fc',
    3,
    'MT1_ST_P3',
    'medium',
    'Mock 1 speaking part 3 (draft).',
    'published'
  )
ON CONFLICT (id) DO NOTHING;

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
ON CONFLICT (id) DO NOTHING;

INSERT INTO bank_sections (id, practice_set_id, module, part, title)
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
ON CONFLICT (id) DO NOTHING;

-- MT1 questions: insert only when (section_id, question_number) is empty.
-- Never updates/deletes existing live MT1 question rows.
INSERT INTO bank_questions (
  id, section_id, question_number, question_type, prompt, options,
  correct_answer, skill_tag, difficulty
)
SELECT v.id, v.section_id, v.question_number, v.question_type, v.prompt, v.options,
       v.correct_answer, v.skill_tag, v.difficulty
FROM (
  VALUES
    (
      'c1230000-0000-4000-8000-000000000311'::uuid,
      'c1200000-0000-4000-8000-000000000031'::uuid,
      1,
      'speaking_part1',
      'Let''s talk about your hometown. Where are you from?',
      '{"kind":"question","prep_sec":0,"video_url":null,"part_label":"Part 1","record_sec":120,"min_skip_sec":5,"speak_time_sec":30}'::jsonb,
      '',
      'speaking',
      'medium'
    ),
    (
      'c1230000-0000-4000-8000-000000000312'::uuid,
      'c1200000-0000-4000-8000-000000000031'::uuid,
      2,
      'speaking_part1',
      'What do you like most about living there?',
      '{"kind":"question","prep_sec":0,"video_url":null,"part_label":"Part 1","record_sec":120,"min_skip_sec":5,"speak_time_sec":30}'::jsonb,
      '',
      'speaking',
      'medium'
    ),
    (
      'c1230000-0000-4000-8000-000000000313'::uuid,
      'c1200000-0000-4000-8000-000000000031'::uuid,
      3,
      'speaking_part1',
      'Has your hometown changed much in recent years?',
      '{"kind":"question","prep_sec":0,"video_url":null,"part_label":"Part 1","record_sec":120,"min_skip_sec":5,"speak_time_sec":30}'::jsonb,
      '',
      'speaking',
      'medium'
    ),
    (
      'c1230000-0000-4000-8000-000000000314'::uuid,
      'c1200000-0000-4000-8000-000000000031'::uuid,
      4,
      'speaking_part1',
      'Would you recommend your hometown to a visitor?',
      '{"kind":"question","prep_sec":0,"video_url":null,"part_label":"Part 1","record_sec":120,"min_skip_sec":5,"speak_time_sec":30}'::jsonb,
      '',
      'speaking',
      'medium'
    ),
    (
      'c1230000-0000-4000-8000-000000000321'::uuid,
      'c1200000-0000-4000-8000-000000000032'::uuid,
      1,
      'speaking_part2',
      $p2$Describe a skill you learned that you are proud of.

You should say:
• what the skill was
• when and how you learned it
• why you are proud of it

and explain how this skill has helped you.$p2$,
      '{"kind":"part2_intro","prep_sec":60,"video_url":null,"part_label":"Part 2","record_sec":120,"min_skip_sec":30,"speak_time_sec":120}'::jsonb,
      '',
      'speaking',
      'medium'
    ),
    (
      'c1230000-0000-4000-8000-000000000331'::uuid,
      'c1200000-0000-4000-8000-000000000033'::uuid,
      1,
      'speaking_part3',
      'Why do you think continuous learning is important?',
      '{"kind":"question","prep_sec":0,"video_url":null,"part_label":"Part 3","record_sec":60,"min_skip_sec":5,"speak_time_sec":45}'::jsonb,
      '',
      'speaking',
      'medium'
    ),
    (
      'c1230000-0000-4000-8000-000000000332'::uuid,
      'c1200000-0000-4000-8000-000000000033'::uuid,
      2,
      'speaking_part3',
      'How has technology changed the way people learn new skills?',
      '{"kind":"question","prep_sec":0,"video_url":null,"part_label":"Part 3","record_sec":60,"min_skip_sec":5,"speak_time_sec":45}'::jsonb,
      '',
      'speaking',
      'medium'
    ),
    (
      'c1230000-0000-4000-8000-000000000333'::uuid,
      'c1200000-0000-4000-8000-000000000033'::uuid,
      3,
      'speaking_part3',
      'Do you think schools prepare students well for real-world skills?',
      '{"kind":"question","prep_sec":0,"video_url":null,"part_label":"Part 3","record_sec":60,"min_skip_sec":5,"speak_time_sec":45}'::jsonb,
      '',
      'speaking',
      'medium'
    )
) AS v(id, section_id, question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty)
WHERE NOT EXISTS (
  SELECT 1
  FROM bank_questions bq
  WHERE bq.section_id = v.section_id
    AND bq.question_number = v.question_number
)
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2) Nine SS_* dummy clones (new IDs only; never touch MT1 ids)
--    set_number 102-104 / 202-204 / 302-304 avoid Bank 4 catalogue 1–3
-- ---------------------------------------------------------------------------
INSERT INTO practice_sets (
  id, bank_id, set_number, title, difficulty, description, status
)
VALUES
  ('c1500000-0000-4000-8000-000000000102', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 102, 'SS_P1_02', 'medium', 'DUMMY/CLONE of MT1_ST_P1 for Speaking Skill inventory (SS_P1_02).', 'published'),
  ('c1500000-0000-4000-8000-000000000103', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 103, 'SS_P1_03', 'medium', 'DUMMY/CLONE of MT1_ST_P1 for Speaking Skill inventory (SS_P1_03).', 'published'),
  ('c1500000-0000-4000-8000-000000000104', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 104, 'SS_P1_04', 'medium', 'DUMMY/CLONE of MT1_ST_P1 for Speaking Skill inventory (SS_P1_04).', 'published'),
  ('c1500000-0000-4000-8000-000000000202', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 202, 'SS_P2_02', 'medium', 'DUMMY/CLONE of MT1_ST_P2 for Speaking Skill inventory (SS_P2_02).', 'published'),
  ('c1500000-0000-4000-8000-000000000203', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 203, 'SS_P2_03', 'medium', 'DUMMY/CLONE of MT1_ST_P2 for Speaking Skill inventory (SS_P2_03).', 'published'),
  ('c1500000-0000-4000-8000-000000000204', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 204, 'SS_P2_04', 'medium', 'DUMMY/CLONE of MT1_ST_P2 for Speaking Skill inventory (SS_P2_04).', 'published'),
  ('c1500000-0000-4000-8000-000000000302', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 302, 'SS_P3_02', 'medium', 'DUMMY/CLONE of MT1_ST_P3 for Speaking Skill inventory (SS_P3_02).', 'published'),
  ('c1500000-0000-4000-8000-000000000303', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 303, 'SS_P3_03', 'medium', 'DUMMY/CLONE of MT1_ST_P3 for Speaking Skill inventory (SS_P3_03).', 'published'),
  ('c1500000-0000-4000-8000-000000000304', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 304, 'SS_P3_04', 'medium', 'DUMMY/CLONE of MT1_ST_P3 for Speaking Skill inventory (SS_P3_04).', 'published')
ON CONFLICT (id) DO UPDATE SET
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  difficulty = EXCLUDED.difficulty,
  status = 'published',
  bank_id = EXCLUDED.bank_id,
  set_number = EXCLUDED.set_number;

INSERT INTO practice_hubs (
  id, set_id, slug, videos, practice_prompt, submit_config, estimated_min, sort_order
)
VALUES
  (
    'c1510000-0000-4000-8000-000000000102',
    'c1500000-0000-4000-8000-000000000102',
    'speaking-ss-p1-02',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"speaking","href":"/practice/speaking/c1510000-0000-4000-8000-000000000102/exercise"}'::jsonb,
    15,
    40
  ),
  (
    'c1510000-0000-4000-8000-000000000103',
    'c1500000-0000-4000-8000-000000000103',
    'speaking-ss-p1-03',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"speaking","href":"/practice/speaking/c1510000-0000-4000-8000-000000000103/exercise"}'::jsonb,
    15,
    41
  ),
  (
    'c1510000-0000-4000-8000-000000000104',
    'c1500000-0000-4000-8000-000000000104',
    'speaking-ss-p1-04',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"speaking","href":"/practice/speaking/c1510000-0000-4000-8000-000000000104/exercise"}'::jsonb,
    15,
    42
  ),
  (
    'c1510000-0000-4000-8000-000000000202',
    'c1500000-0000-4000-8000-000000000202',
    'speaking-ss-p2-02',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"speaking","href":"/practice/speaking/c1510000-0000-4000-8000-000000000202/exercise"}'::jsonb,
    15,
    43
  ),
  (
    'c1510000-0000-4000-8000-000000000203',
    'c1500000-0000-4000-8000-000000000203',
    'speaking-ss-p2-03',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"speaking","href":"/practice/speaking/c1510000-0000-4000-8000-000000000203/exercise"}'::jsonb,
    15,
    44
  ),
  (
    'c1510000-0000-4000-8000-000000000204',
    'c1500000-0000-4000-8000-000000000204',
    'speaking-ss-p2-04',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"speaking","href":"/practice/speaking/c1510000-0000-4000-8000-000000000204/exercise"}'::jsonb,
    15,
    45
  ),
  (
    'c1510000-0000-4000-8000-000000000302',
    'c1500000-0000-4000-8000-000000000302',
    'speaking-ss-p3-02',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"speaking","href":"/practice/speaking/c1510000-0000-4000-8000-000000000302/exercise"}'::jsonb,
    15,
    46
  ),
  (
    'c1510000-0000-4000-8000-000000000303',
    'c1500000-0000-4000-8000-000000000303',
    'speaking-ss-p3-03',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"speaking","href":"/practice/speaking/c1510000-0000-4000-8000-000000000303/exercise"}'::jsonb,
    15,
    47
  ),
  (
    'c1510000-0000-4000-8000-000000000304',
    'c1500000-0000-4000-8000-000000000304',
    'speaking-ss-p3-04',
    '[]'::jsonb,
    '',
    '{"type":"bank","module":"speaking","href":"/practice/speaking/c1510000-0000-4000-8000-000000000304/exercise"}'::jsonb,
    15,
    48
  )
ON CONFLICT (id) DO UPDATE SET
  slug = EXCLUDED.slug,
  submit_config = EXCLUDED.submit_config,
  estimated_min = EXCLUDED.estimated_min,
  sort_order = EXCLUDED.sort_order,
  set_id = EXCLUDED.set_id;

INSERT INTO bank_sections (id, practice_set_id, module, part, title)
VALUES
  ('c1520000-0000-4000-8000-000000000102', 'c1500000-0000-4000-8000-000000000102', 'speaking', 1, 'SS_P1_02'),
  ('c1520000-0000-4000-8000-000000000103', 'c1500000-0000-4000-8000-000000000103', 'speaking', 1, 'SS_P1_03'),
  ('c1520000-0000-4000-8000-000000000104', 'c1500000-0000-4000-8000-000000000104', 'speaking', 1, 'SS_P1_04'),
  ('c1520000-0000-4000-8000-000000000202', 'c1500000-0000-4000-8000-000000000202', 'speaking', 1, 'SS_P2_02'),
  ('c1520000-0000-4000-8000-000000000203', 'c1500000-0000-4000-8000-000000000203', 'speaking', 1, 'SS_P2_03'),
  ('c1520000-0000-4000-8000-000000000204', 'c1500000-0000-4000-8000-000000000204', 'speaking', 1, 'SS_P2_04'),
  ('c1520000-0000-4000-8000-000000000302', 'c1500000-0000-4000-8000-000000000302', 'speaking', 1, 'SS_P3_02'),
  ('c1520000-0000-4000-8000-000000000303', 'c1500000-0000-4000-8000-000000000303', 'speaking', 1, 'SS_P3_03'),
  ('c1520000-0000-4000-8000-000000000304', 'c1500000-0000-4000-8000-000000000304', 'speaking', 1, 'SS_P3_04')
ON CONFLICT (id) DO UPDATE SET
  title = EXCLUDED.title,
  practice_set_id = EXCLUDED.practice_set_id,
  module = EXCLUDED.module,
  part = EXCLUDED.part;

-- Clone questions from MT1 templates (prefer live section content; fallback embedded)
WITH src_p1 AS (
  SELECT question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty
  FROM bank_questions
  WHERE section_id = 'c1200000-0000-4000-8000-000000000031'
),
src_p2 AS (
  SELECT question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty
  FROM bank_questions
  WHERE section_id = 'c1200000-0000-4000-8000-000000000032'
),
src_p3 AS (
  SELECT question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty
  FROM bank_questions
  WHERE section_id = 'c1200000-0000-4000-8000-000000000033'
),
targets AS (
  SELECT * FROM (VALUES
    ('c1520000-0000-4000-8000-000000000102'::uuid, 'c1530000-0000-4000-8000-000000010201'::uuid, 1, 'p1'),
    ('c1520000-0000-4000-8000-000000000102'::uuid, 'c1530000-0000-4000-8000-000000010202'::uuid, 2, 'p1'),
    ('c1520000-0000-4000-8000-000000000102'::uuid, 'c1530000-0000-4000-8000-000000010203'::uuid, 3, 'p1'),
    ('c1520000-0000-4000-8000-000000000102'::uuid, 'c1530000-0000-4000-8000-000000010204'::uuid, 4, 'p1'),
    ('c1520000-0000-4000-8000-000000000103'::uuid, 'c1530000-0000-4000-8000-000000010301'::uuid, 1, 'p1'),
    ('c1520000-0000-4000-8000-000000000103'::uuid, 'c1530000-0000-4000-8000-000000010302'::uuid, 2, 'p1'),
    ('c1520000-0000-4000-8000-000000000103'::uuid, 'c1530000-0000-4000-8000-000000010303'::uuid, 3, 'p1'),
    ('c1520000-0000-4000-8000-000000000103'::uuid, 'c1530000-0000-4000-8000-000000010304'::uuid, 4, 'p1'),
    ('c1520000-0000-4000-8000-000000000104'::uuid, 'c1530000-0000-4000-8000-000000010401'::uuid, 1, 'p1'),
    ('c1520000-0000-4000-8000-000000000104'::uuid, 'c1530000-0000-4000-8000-000000010402'::uuid, 2, 'p1'),
    ('c1520000-0000-4000-8000-000000000104'::uuid, 'c1530000-0000-4000-8000-000000010403'::uuid, 3, 'p1'),
    ('c1520000-0000-4000-8000-000000000104'::uuid, 'c1530000-0000-4000-8000-000000010404'::uuid, 4, 'p1'),
    ('c1520000-0000-4000-8000-000000000202'::uuid, 'c1530000-0000-4000-8000-000000020201'::uuid, 1, 'p2'),
    ('c1520000-0000-4000-8000-000000000203'::uuid, 'c1530000-0000-4000-8000-000000020301'::uuid, 1, 'p2'),
    ('c1520000-0000-4000-8000-000000000204'::uuid, 'c1530000-0000-4000-8000-000000020401'::uuid, 1, 'p2'),
    ('c1520000-0000-4000-8000-000000000302'::uuid, 'c1530000-0000-4000-8000-000000030201'::uuid, 1, 'p3'),
    ('c1520000-0000-4000-8000-000000000302'::uuid, 'c1530000-0000-4000-8000-000000030202'::uuid, 2, 'p3'),
    ('c1520000-0000-4000-8000-000000000302'::uuid, 'c1530000-0000-4000-8000-000000030203'::uuid, 3, 'p3'),
    ('c1520000-0000-4000-8000-000000000303'::uuid, 'c1530000-0000-4000-8000-000000030301'::uuid, 1, 'p3'),
    ('c1520000-0000-4000-8000-000000000303'::uuid, 'c1530000-0000-4000-8000-000000030302'::uuid, 2, 'p3'),
    ('c1520000-0000-4000-8000-000000000303'::uuid, 'c1530000-0000-4000-8000-000000030303'::uuid, 3, 'p3'),
    ('c1520000-0000-4000-8000-000000000304'::uuid, 'c1530000-0000-4000-8000-000000030401'::uuid, 1, 'p3'),
    ('c1520000-0000-4000-8000-000000000304'::uuid, 'c1530000-0000-4000-8000-000000030402'::uuid, 2, 'p3'),
    ('c1520000-0000-4000-8000-000000000304'::uuid, 'c1530000-0000-4000-8000-000000030403'::uuid, 3, 'p3')
  ) AS t(section_id, question_id, question_number, part_key)
),
resolved AS (
  SELECT
    t.question_id,
    t.section_id,
    t.question_number,
    COALESCE(s.question_type, CASE t.part_key
      WHEN 'p1' THEN 'speaking_part1'
      WHEN 'p2' THEN 'speaking_part2'
      ELSE 'speaking_part3'
    END) AS question_type,
    COALESCE(s.prompt, '') AS prompt,
    COALESCE(s.options, '{}'::jsonb) AS options,
    COALESCE(s.correct_answer, '') AS correct_answer,
    COALESCE(s.skill_tag, 'speaking') AS skill_tag,
    COALESCE(s.difficulty, 'medium') AS difficulty
  FROM targets t
  LEFT JOIN src_p1 s ON t.part_key = 'p1' AND s.question_number = t.question_number
  WHERE t.part_key = 'p1'
  UNION ALL
  SELECT
    t.question_id,
    t.section_id,
    t.question_number,
    COALESCE(s.question_type, 'speaking_part2'),
    COALESCE(s.prompt, ''),
    COALESCE(s.options, '{}'::jsonb),
    COALESCE(s.correct_answer, ''),
    COALESCE(s.skill_tag, 'speaking'),
    COALESCE(s.difficulty, 'medium')
  FROM targets t
  LEFT JOIN src_p2 s ON t.part_key = 'p2' AND s.question_number = t.question_number
  WHERE t.part_key = 'p2'
  UNION ALL
  SELECT
    t.question_id,
    t.section_id,
    t.question_number,
    COALESCE(s.question_type, 'speaking_part3'),
    COALESCE(s.prompt, ''),
    COALESCE(s.options, '{}'::jsonb),
    COALESCE(s.correct_answer, ''),
    COALESCE(s.skill_tag, 'speaking'),
    COALESCE(s.difficulty, 'medium')
  FROM targets t
  LEFT JOIN src_p3 s ON t.part_key = 'p3' AND s.question_number = t.question_number
  WHERE t.part_key = 'p3'
)
INSERT INTO bank_questions (
  id, section_id, question_number, question_type, prompt, options,
  correct_answer, skill_tag, difficulty
)
SELECT
  question_id, section_id, question_number, question_type, prompt, options,
  correct_answer, skill_tag, difficulty
FROM resolved
WHERE length(trim(prompt)) > 0
ON CONFLICT (id) DO UPDATE SET
  section_id = EXCLUDED.section_id,
  question_number = EXCLUDED.question_number,
  question_type = EXCLUDED.question_type,
  prompt = EXCLUDED.prompt,
  options = EXCLUDED.options,
  correct_answer = EXCLUDED.correct_answer,
  skill_tag = EXCLUDED.skill_tag,
  difficulty = EXCLUDED.difficulty;
