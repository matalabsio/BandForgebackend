-- Replace dummy Speaking Bank 4 with Society & Culture part sets (15 hubs).
-- Each theme × Part 1/2/3; questions+video_url copied from SC mock tests.

DELETE FROM user_practice_assignments
WHERE practice_set_id IN (
  SELECT id FROM practice_sets WHERE bank_id = 'fa62779b-148c-401d-b66d-5a7e4fbba6fc'
)
OR hub_id IN (
  SELECT ph.id FROM practice_hubs ph
  JOIN practice_sets ps ON ps.id = ph.set_id
  WHERE ps.bank_id = 'fa62779b-148c-401d-b66d-5a7e4fbba6fc'
);

DELETE FROM program_content_items
WHERE plan_id = (SELECT id FROM plans WHERE slug = 'speaking_skill' LIMIT 1)
  AND item_type = 'practice_hub';

DELETE FROM practice_sets
WHERE bank_id = 'fa62779b-148c-401d-b66d-5a7e4fbba6fc';

DELETE FROM user_practice_assignments
WHERE practice_set_id = 'caa62feb-5283-4e26-a300-9824d5c0832c'
   OR hub_id IN (SELECT id FROM practice_hubs WHERE set_id = 'caa62feb-5283-4e26-a300-9824d5c0832c');
DELETE FROM program_content_items WHERE item_id = 'caa62feb-5283-4e26-a300-9824d5c0832c';
DELETE FROM practice_sets WHERE id = 'caa62feb-5283-4e26-a300-9824d5c0832c';

INSERT INTO practice_sets (id, bank_id, set_number, title, difficulty, description, status)
VALUES
  ('c1600000-0000-4000-8000-000000010100', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 1, 'Community — Part 1', 'medium', 'Society & Culture — Community Part 1 (examiner videos).', 'published'),
  ('c1600000-0000-4000-8000-000000010200', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 2, 'Community — Part 2', 'medium', 'Society & Culture — Community Part 2 (examiner videos).', 'published'),
  ('c1600000-0000-4000-8000-000000010300', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 3, 'Community — Part 3', 'medium', 'Society & Culture — Community Part 3 (examiner videos).', 'published'),
  ('c1600000-0000-4000-8000-000000020100', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 4, 'Festivals — Part 1', 'medium', 'Society & Culture — Festivals Part 1 (examiner videos).', 'published'),
  ('c1600000-0000-4000-8000-000000020200', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 5, 'Festivals — Part 2', 'medium', 'Society & Culture — Festivals Part 2 (examiner videos).', 'published'),
  ('c1600000-0000-4000-8000-000000020300', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 6, 'Festivals — Part 3', 'medium', 'Society & Culture — Festivals Part 3 (examiner videos).', 'published'),
  ('c1600000-0000-4000-8000-000000030100', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 7, 'Social Media — Part 1', 'medium', 'Society & Culture — Social Media Part 1 (examiner videos).', 'published'),
  ('c1600000-0000-4000-8000-000000030200', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 8, 'Social Media — Part 2', 'medium', 'Society & Culture — Social Media Part 2 (examiner videos).', 'published'),
  ('c1600000-0000-4000-8000-000000030300', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 9, 'Social Media — Part 3', 'medium', 'Society & Culture — Social Media Part 3 (examiner videos).', 'published'),
  ('c1600000-0000-4000-8000-000000040100', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 10, 'Media & News — Part 1', 'medium', 'Society & Culture — Media & News Part 1 (examiner videos).', 'published'),
  ('c1600000-0000-4000-8000-000000040200', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 11, 'Media & News — Part 2', 'medium', 'Society & Culture — Media & News Part 2 (examiner videos).', 'published'),
  ('c1600000-0000-4000-8000-000000040300', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 12, 'Media & News — Part 3', 'medium', 'Society & Culture — Media & News Part 3 (examiner videos).', 'published'),
  ('c1600000-0000-4000-8000-000000050100', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 13, 'Family — Part 1', 'medium', 'Society & Culture — Family Part 1 (examiner videos).', 'published'),
  ('c1600000-0000-4000-8000-000000050200', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 14, 'Family — Part 2', 'medium', 'Society & Culture — Family Part 2 (examiner videos).', 'published'),
  ('c1600000-0000-4000-8000-000000050300', 'fa62779b-148c-401d-b66d-5a7e4fbba6fc', 15, 'Family — Part 3', 'medium', 'Society & Culture — Family Part 3 (examiner videos).', 'published');

INSERT INTO practice_hubs (id, set_id, slug, videos, practice_prompt, submit_config, estimated_min, sort_order)
VALUES
  ('c1610000-0000-4000-8000-000000010100', 'c1600000-0000-4000-8000-000000010100', 'speaking-sc-t1-p1', '[]'::jsonb, '', '{"type":"bank","module":"speaking","href":"/practice/speaking/c1610000-0000-4000-8000-000000010100/exercise"}'::jsonb, 15, 1),
  ('c1610000-0000-4000-8000-000000010200', 'c1600000-0000-4000-8000-000000010200', 'speaking-sc-t1-p2', '[]'::jsonb, '', '{"type":"bank","module":"speaking","href":"/practice/speaking/c1610000-0000-4000-8000-000000010200/exercise"}'::jsonb, 15, 2),
  ('c1610000-0000-4000-8000-000000010300', 'c1600000-0000-4000-8000-000000010300', 'speaking-sc-t1-p3', '[]'::jsonb, '', '{"type":"bank","module":"speaking","href":"/practice/speaking/c1610000-0000-4000-8000-000000010300/exercise"}'::jsonb, 15, 3),
  ('c1610000-0000-4000-8000-000000020100', 'c1600000-0000-4000-8000-000000020100', 'speaking-sc-t2-p1', '[]'::jsonb, '', '{"type":"bank","module":"speaking","href":"/practice/speaking/c1610000-0000-4000-8000-000000020100/exercise"}'::jsonb, 15, 4),
  ('c1610000-0000-4000-8000-000000020200', 'c1600000-0000-4000-8000-000000020200', 'speaking-sc-t2-p2', '[]'::jsonb, '', '{"type":"bank","module":"speaking","href":"/practice/speaking/c1610000-0000-4000-8000-000000020200/exercise"}'::jsonb, 15, 5),
  ('c1610000-0000-4000-8000-000000020300', 'c1600000-0000-4000-8000-000000020300', 'speaking-sc-t2-p3', '[]'::jsonb, '', '{"type":"bank","module":"speaking","href":"/practice/speaking/c1610000-0000-4000-8000-000000020300/exercise"}'::jsonb, 15, 6),
  ('c1610000-0000-4000-8000-000000030100', 'c1600000-0000-4000-8000-000000030100', 'speaking-sc-t3-p1', '[]'::jsonb, '', '{"type":"bank","module":"speaking","href":"/practice/speaking/c1610000-0000-4000-8000-000000030100/exercise"}'::jsonb, 15, 7),
  ('c1610000-0000-4000-8000-000000030200', 'c1600000-0000-4000-8000-000000030200', 'speaking-sc-t3-p2', '[]'::jsonb, '', '{"type":"bank","module":"speaking","href":"/practice/speaking/c1610000-0000-4000-8000-000000030200/exercise"}'::jsonb, 15, 8),
  ('c1610000-0000-4000-8000-000000030300', 'c1600000-0000-4000-8000-000000030300', 'speaking-sc-t3-p3', '[]'::jsonb, '', '{"type":"bank","module":"speaking","href":"/practice/speaking/c1610000-0000-4000-8000-000000030300/exercise"}'::jsonb, 15, 9),
  ('c1610000-0000-4000-8000-000000040100', 'c1600000-0000-4000-8000-000000040100', 'speaking-sc-t4-p1', '[]'::jsonb, '', '{"type":"bank","module":"speaking","href":"/practice/speaking/c1610000-0000-4000-8000-000000040100/exercise"}'::jsonb, 15, 10),
  ('c1610000-0000-4000-8000-000000040200', 'c1600000-0000-4000-8000-000000040200', 'speaking-sc-t4-p2', '[]'::jsonb, '', '{"type":"bank","module":"speaking","href":"/practice/speaking/c1610000-0000-4000-8000-000000040200/exercise"}'::jsonb, 15, 11),
  ('c1610000-0000-4000-8000-000000040300', 'c1600000-0000-4000-8000-000000040300', 'speaking-sc-t4-p3', '[]'::jsonb, '', '{"type":"bank","module":"speaking","href":"/practice/speaking/c1610000-0000-4000-8000-000000040300/exercise"}'::jsonb, 15, 12),
  ('c1610000-0000-4000-8000-000000050100', 'c1600000-0000-4000-8000-000000050100', 'speaking-sc-t5-p1', '[]'::jsonb, '', '{"type":"bank","module":"speaking","href":"/practice/speaking/c1610000-0000-4000-8000-000000050100/exercise"}'::jsonb, 15, 13),
  ('c1610000-0000-4000-8000-000000050200', 'c1600000-0000-4000-8000-000000050200', 'speaking-sc-t5-p2', '[]'::jsonb, '', '{"type":"bank","module":"speaking","href":"/practice/speaking/c1610000-0000-4000-8000-000000050200/exercise"}'::jsonb, 15, 14),
  ('c1610000-0000-4000-8000-000000050300', 'c1600000-0000-4000-8000-000000050300', 'speaking-sc-t5-p3', '[]'::jsonb, '', '{"type":"bank","module":"speaking","href":"/practice/speaking/c1610000-0000-4000-8000-000000050300/exercise"}'::jsonb, 15, 15);

INSERT INTO bank_sections (id, practice_set_id, module, part, title)
VALUES
  ('c1620000-0000-4000-8000-000000010100', 'c1600000-0000-4000-8000-000000010100', 'speaking', 1, 'Community — Part 1'),
  ('c1620000-0000-4000-8000-000000010200', 'c1600000-0000-4000-8000-000000010200', 'speaking', 2, 'Community — Part 2'),
  ('c1620000-0000-4000-8000-000000010300', 'c1600000-0000-4000-8000-000000010300', 'speaking', 3, 'Community — Part 3'),
  ('c1620000-0000-4000-8000-000000020100', 'c1600000-0000-4000-8000-000000020100', 'speaking', 1, 'Festivals — Part 1'),
  ('c1620000-0000-4000-8000-000000020200', 'c1600000-0000-4000-8000-000000020200', 'speaking', 2, 'Festivals — Part 2'),
  ('c1620000-0000-4000-8000-000000020300', 'c1600000-0000-4000-8000-000000020300', 'speaking', 3, 'Festivals — Part 3'),
  ('c1620000-0000-4000-8000-000000030100', 'c1600000-0000-4000-8000-000000030100', 'speaking', 1, 'Social Media — Part 1'),
  ('c1620000-0000-4000-8000-000000030200', 'c1600000-0000-4000-8000-000000030200', 'speaking', 2, 'Social Media — Part 2'),
  ('c1620000-0000-4000-8000-000000030300', 'c1600000-0000-4000-8000-000000030300', 'speaking', 3, 'Social Media — Part 3'),
  ('c1620000-0000-4000-8000-000000040100', 'c1600000-0000-4000-8000-000000040100', 'speaking', 1, 'Media & News — Part 1'),
  ('c1620000-0000-4000-8000-000000040200', 'c1600000-0000-4000-8000-000000040200', 'speaking', 2, 'Media & News — Part 2'),
  ('c1620000-0000-4000-8000-000000040300', 'c1600000-0000-4000-8000-000000040300', 'speaking', 3, 'Media & News — Part 3'),
  ('c1620000-0000-4000-8000-000000050100', 'c1600000-0000-4000-8000-000000050100', 'speaking', 1, 'Family — Part 1'),
  ('c1620000-0000-4000-8000-000000050200', 'c1600000-0000-4000-8000-000000050200', 'speaking', 2, 'Family — Part 2'),
  ('c1620000-0000-4000-8000-000000050300', 'c1600000-0000-4000-8000-000000050300', 'speaking', 3, 'Family — Part 3');

-- SC_Community Part 1
INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty
)
SELECT
  'c1620000-0000-4000-8000-000000010100'::uuid,
  q.question_number,
  q.question_type,
  q.prompt,
  jsonb_build_object(
    'kind', COALESCE(q.options->>'kind', CASE WHEN q.part = 2 THEN 'part2_intro' ELSE 'question' END),
    'part_label', 'Part ' || q.part::text,
    'speak_time_sec', CASE q.part WHEN 1 THEN 30 WHEN 2 THEN 120 ELSE 45 END,
    'min_skip_sec', CASE WHEN q.part = 2 THEN 30 ELSE 5 END,
    'prep_sec', CASE WHEN q.part = 2 THEN 60 ELSE 0 END,
    'record_sec', CASE q.part WHEN 1 THEN 120 WHEN 2 THEN 120 ELSE 60 END,
    'video_url', q.options->>'video_url',
    'video_asset', q.options->>'video_asset'
  ),
  '',
  'speaking',
  'medium'
FROM questions q
WHERE q.mock_test_id = 'a1000000-0000-4000-8000-000000000001'
  AND q.module = 'speaking'
  AND q.part = 1;

-- SC_Community Part 2
INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty
)
SELECT
  'c1620000-0000-4000-8000-000000010200'::uuid,
  q.question_number,
  q.question_type,
  q.prompt,
  jsonb_build_object(
    'kind', COALESCE(q.options->>'kind', CASE WHEN q.part = 2 THEN 'part2_intro' ELSE 'question' END),
    'part_label', 'Part ' || q.part::text,
    'speak_time_sec', CASE q.part WHEN 1 THEN 30 WHEN 2 THEN 120 ELSE 45 END,
    'min_skip_sec', CASE WHEN q.part = 2 THEN 30 ELSE 5 END,
    'prep_sec', CASE WHEN q.part = 2 THEN 60 ELSE 0 END,
    'record_sec', CASE q.part WHEN 1 THEN 120 WHEN 2 THEN 120 ELSE 60 END,
    'video_url', q.options->>'video_url',
    'video_asset', q.options->>'video_asset'
  ),
  '',
  'speaking',
  'medium'
FROM questions q
WHERE q.mock_test_id = 'a1000000-0000-4000-8000-000000000001'
  AND q.module = 'speaking'
  AND q.part = 2;

-- SC_Community Part 3
INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty
)
SELECT
  'c1620000-0000-4000-8000-000000010300'::uuid,
  q.question_number,
  q.question_type,
  q.prompt,
  jsonb_build_object(
    'kind', COALESCE(q.options->>'kind', CASE WHEN q.part = 2 THEN 'part2_intro' ELSE 'question' END),
    'part_label', 'Part ' || q.part::text,
    'speak_time_sec', CASE q.part WHEN 1 THEN 30 WHEN 2 THEN 120 ELSE 45 END,
    'min_skip_sec', CASE WHEN q.part = 2 THEN 30 ELSE 5 END,
    'prep_sec', CASE WHEN q.part = 2 THEN 60 ELSE 0 END,
    'record_sec', CASE q.part WHEN 1 THEN 120 WHEN 2 THEN 120 ELSE 60 END,
    'video_url', q.options->>'video_url',
    'video_asset', q.options->>'video_asset'
  ),
  '',
  'speaking',
  'medium'
FROM questions q
WHERE q.mock_test_id = 'a1000000-0000-4000-8000-000000000001'
  AND q.module = 'speaking'
  AND q.part = 3;

-- SC_Festivals Part 1
INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty
)
SELECT
  'c1620000-0000-4000-8000-000000020100'::uuid,
  q.question_number,
  q.question_type,
  q.prompt,
  jsonb_build_object(
    'kind', COALESCE(q.options->>'kind', CASE WHEN q.part = 2 THEN 'part2_intro' ELSE 'question' END),
    'part_label', 'Part ' || q.part::text,
    'speak_time_sec', CASE q.part WHEN 1 THEN 30 WHEN 2 THEN 120 ELSE 45 END,
    'min_skip_sec', CASE WHEN q.part = 2 THEN 30 ELSE 5 END,
    'prep_sec', CASE WHEN q.part = 2 THEN 60 ELSE 0 END,
    'record_sec', CASE q.part WHEN 1 THEN 120 WHEN 2 THEN 120 ELSE 60 END,
    'video_url', q.options->>'video_url',
    'video_asset', q.options->>'video_asset'
  ),
  '',
  'speaking',
  'medium'
FROM questions q
WHERE q.mock_test_id = 'a1000000-0000-4000-8000-000000000002'
  AND q.module = 'speaking'
  AND q.part = 1;

-- SC_Festivals Part 2
INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty
)
SELECT
  'c1620000-0000-4000-8000-000000020200'::uuid,
  q.question_number,
  q.question_type,
  q.prompt,
  jsonb_build_object(
    'kind', COALESCE(q.options->>'kind', CASE WHEN q.part = 2 THEN 'part2_intro' ELSE 'question' END),
    'part_label', 'Part ' || q.part::text,
    'speak_time_sec', CASE q.part WHEN 1 THEN 30 WHEN 2 THEN 120 ELSE 45 END,
    'min_skip_sec', CASE WHEN q.part = 2 THEN 30 ELSE 5 END,
    'prep_sec', CASE WHEN q.part = 2 THEN 60 ELSE 0 END,
    'record_sec', CASE q.part WHEN 1 THEN 120 WHEN 2 THEN 120 ELSE 60 END,
    'video_url', q.options->>'video_url',
    'video_asset', q.options->>'video_asset'
  ),
  '',
  'speaking',
  'medium'
FROM questions q
WHERE q.mock_test_id = 'a1000000-0000-4000-8000-000000000002'
  AND q.module = 'speaking'
  AND q.part = 2;

-- SC_Festivals Part 3
INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty
)
SELECT
  'c1620000-0000-4000-8000-000000020300'::uuid,
  q.question_number,
  q.question_type,
  q.prompt,
  jsonb_build_object(
    'kind', COALESCE(q.options->>'kind', CASE WHEN q.part = 2 THEN 'part2_intro' ELSE 'question' END),
    'part_label', 'Part ' || q.part::text,
    'speak_time_sec', CASE q.part WHEN 1 THEN 30 WHEN 2 THEN 120 ELSE 45 END,
    'min_skip_sec', CASE WHEN q.part = 2 THEN 30 ELSE 5 END,
    'prep_sec', CASE WHEN q.part = 2 THEN 60 ELSE 0 END,
    'record_sec', CASE q.part WHEN 1 THEN 120 WHEN 2 THEN 120 ELSE 60 END,
    'video_url', q.options->>'video_url',
    'video_asset', q.options->>'video_asset'
  ),
  '',
  'speaking',
  'medium'
FROM questions q
WHERE q.mock_test_id = 'a1000000-0000-4000-8000-000000000002'
  AND q.module = 'speaking'
  AND q.part = 3;

-- SC_SocialMedia Part 1
INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty
)
SELECT
  'c1620000-0000-4000-8000-000000030100'::uuid,
  q.question_number,
  q.question_type,
  q.prompt,
  jsonb_build_object(
    'kind', COALESCE(q.options->>'kind', CASE WHEN q.part = 2 THEN 'part2_intro' ELSE 'question' END),
    'part_label', 'Part ' || q.part::text,
    'speak_time_sec', CASE q.part WHEN 1 THEN 30 WHEN 2 THEN 120 ELSE 45 END,
    'min_skip_sec', CASE WHEN q.part = 2 THEN 30 ELSE 5 END,
    'prep_sec', CASE WHEN q.part = 2 THEN 60 ELSE 0 END,
    'record_sec', CASE q.part WHEN 1 THEN 120 WHEN 2 THEN 120 ELSE 60 END,
    'video_url', q.options->>'video_url',
    'video_asset', q.options->>'video_asset'
  ),
  '',
  'speaking',
  'medium'
FROM questions q
WHERE q.mock_test_id = 'a1000000-0000-4000-8000-000000000003'
  AND q.module = 'speaking'
  AND q.part = 1;

-- SC_SocialMedia Part 2
INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty
)
SELECT
  'c1620000-0000-4000-8000-000000030200'::uuid,
  q.question_number,
  q.question_type,
  q.prompt,
  jsonb_build_object(
    'kind', COALESCE(q.options->>'kind', CASE WHEN q.part = 2 THEN 'part2_intro' ELSE 'question' END),
    'part_label', 'Part ' || q.part::text,
    'speak_time_sec', CASE q.part WHEN 1 THEN 30 WHEN 2 THEN 120 ELSE 45 END,
    'min_skip_sec', CASE WHEN q.part = 2 THEN 30 ELSE 5 END,
    'prep_sec', CASE WHEN q.part = 2 THEN 60 ELSE 0 END,
    'record_sec', CASE q.part WHEN 1 THEN 120 WHEN 2 THEN 120 ELSE 60 END,
    'video_url', q.options->>'video_url',
    'video_asset', q.options->>'video_asset'
  ),
  '',
  'speaking',
  'medium'
FROM questions q
WHERE q.mock_test_id = 'a1000000-0000-4000-8000-000000000003'
  AND q.module = 'speaking'
  AND q.part = 2;

-- SC_SocialMedia Part 3
INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty
)
SELECT
  'c1620000-0000-4000-8000-000000030300'::uuid,
  q.question_number,
  q.question_type,
  q.prompt,
  jsonb_build_object(
    'kind', COALESCE(q.options->>'kind', CASE WHEN q.part = 2 THEN 'part2_intro' ELSE 'question' END),
    'part_label', 'Part ' || q.part::text,
    'speak_time_sec', CASE q.part WHEN 1 THEN 30 WHEN 2 THEN 120 ELSE 45 END,
    'min_skip_sec', CASE WHEN q.part = 2 THEN 30 ELSE 5 END,
    'prep_sec', CASE WHEN q.part = 2 THEN 60 ELSE 0 END,
    'record_sec', CASE q.part WHEN 1 THEN 120 WHEN 2 THEN 120 ELSE 60 END,
    'video_url', q.options->>'video_url',
    'video_asset', q.options->>'video_asset'
  ),
  '',
  'speaking',
  'medium'
FROM questions q
WHERE q.mock_test_id = 'a1000000-0000-4000-8000-000000000003'
  AND q.module = 'speaking'
  AND q.part = 3;

-- SC_MediaNews Part 1
INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty
)
SELECT
  'c1620000-0000-4000-8000-000000040100'::uuid,
  q.question_number,
  q.question_type,
  q.prompt,
  jsonb_build_object(
    'kind', COALESCE(q.options->>'kind', CASE WHEN q.part = 2 THEN 'part2_intro' ELSE 'question' END),
    'part_label', 'Part ' || q.part::text,
    'speak_time_sec', CASE q.part WHEN 1 THEN 30 WHEN 2 THEN 120 ELSE 45 END,
    'min_skip_sec', CASE WHEN q.part = 2 THEN 30 ELSE 5 END,
    'prep_sec', CASE WHEN q.part = 2 THEN 60 ELSE 0 END,
    'record_sec', CASE q.part WHEN 1 THEN 120 WHEN 2 THEN 120 ELSE 60 END,
    'video_url', q.options->>'video_url',
    'video_asset', q.options->>'video_asset'
  ),
  '',
  'speaking',
  'medium'
FROM questions q
WHERE q.mock_test_id = 'a1000000-0000-4000-8000-000000000004'
  AND q.module = 'speaking'
  AND q.part = 1;

-- SC_MediaNews Part 2
INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty
)
SELECT
  'c1620000-0000-4000-8000-000000040200'::uuid,
  q.question_number,
  q.question_type,
  q.prompt,
  jsonb_build_object(
    'kind', COALESCE(q.options->>'kind', CASE WHEN q.part = 2 THEN 'part2_intro' ELSE 'question' END),
    'part_label', 'Part ' || q.part::text,
    'speak_time_sec', CASE q.part WHEN 1 THEN 30 WHEN 2 THEN 120 ELSE 45 END,
    'min_skip_sec', CASE WHEN q.part = 2 THEN 30 ELSE 5 END,
    'prep_sec', CASE WHEN q.part = 2 THEN 60 ELSE 0 END,
    'record_sec', CASE q.part WHEN 1 THEN 120 WHEN 2 THEN 120 ELSE 60 END,
    'video_url', q.options->>'video_url',
    'video_asset', q.options->>'video_asset'
  ),
  '',
  'speaking',
  'medium'
FROM questions q
WHERE q.mock_test_id = 'a1000000-0000-4000-8000-000000000004'
  AND q.module = 'speaking'
  AND q.part = 2;

-- SC_MediaNews Part 3
INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty
)
SELECT
  'c1620000-0000-4000-8000-000000040300'::uuid,
  q.question_number,
  q.question_type,
  q.prompt,
  jsonb_build_object(
    'kind', COALESCE(q.options->>'kind', CASE WHEN q.part = 2 THEN 'part2_intro' ELSE 'question' END),
    'part_label', 'Part ' || q.part::text,
    'speak_time_sec', CASE q.part WHEN 1 THEN 30 WHEN 2 THEN 120 ELSE 45 END,
    'min_skip_sec', CASE WHEN q.part = 2 THEN 30 ELSE 5 END,
    'prep_sec', CASE WHEN q.part = 2 THEN 60 ELSE 0 END,
    'record_sec', CASE q.part WHEN 1 THEN 120 WHEN 2 THEN 120 ELSE 60 END,
    'video_url', q.options->>'video_url',
    'video_asset', q.options->>'video_asset'
  ),
  '',
  'speaking',
  'medium'
FROM questions q
WHERE q.mock_test_id = 'a1000000-0000-4000-8000-000000000004'
  AND q.module = 'speaking'
  AND q.part = 3;

-- SC_Family Part 1
INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty
)
SELECT
  'c1620000-0000-4000-8000-000000050100'::uuid,
  q.question_number,
  q.question_type,
  q.prompt,
  jsonb_build_object(
    'kind', COALESCE(q.options->>'kind', CASE WHEN q.part = 2 THEN 'part2_intro' ELSE 'question' END),
    'part_label', 'Part ' || q.part::text,
    'speak_time_sec', CASE q.part WHEN 1 THEN 30 WHEN 2 THEN 120 ELSE 45 END,
    'min_skip_sec', CASE WHEN q.part = 2 THEN 30 ELSE 5 END,
    'prep_sec', CASE WHEN q.part = 2 THEN 60 ELSE 0 END,
    'record_sec', CASE q.part WHEN 1 THEN 120 WHEN 2 THEN 120 ELSE 60 END,
    'video_url', q.options->>'video_url',
    'video_asset', q.options->>'video_asset'
  ),
  '',
  'speaking',
  'medium'
FROM questions q
WHERE q.mock_test_id = 'a1000000-0000-4000-8000-000000000005'
  AND q.module = 'speaking'
  AND q.part = 1;

-- SC_Family Part 2
INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty
)
SELECT
  'c1620000-0000-4000-8000-000000050200'::uuid,
  q.question_number,
  q.question_type,
  q.prompt,
  jsonb_build_object(
    'kind', COALESCE(q.options->>'kind', CASE WHEN q.part = 2 THEN 'part2_intro' ELSE 'question' END),
    'part_label', 'Part ' || q.part::text,
    'speak_time_sec', CASE q.part WHEN 1 THEN 30 WHEN 2 THEN 120 ELSE 45 END,
    'min_skip_sec', CASE WHEN q.part = 2 THEN 30 ELSE 5 END,
    'prep_sec', CASE WHEN q.part = 2 THEN 60 ELSE 0 END,
    'record_sec', CASE q.part WHEN 1 THEN 120 WHEN 2 THEN 120 ELSE 60 END,
    'video_url', q.options->>'video_url',
    'video_asset', q.options->>'video_asset'
  ),
  '',
  'speaking',
  'medium'
FROM questions q
WHERE q.mock_test_id = 'a1000000-0000-4000-8000-000000000005'
  AND q.module = 'speaking'
  AND q.part = 2;

-- SC_Family Part 3
INSERT INTO bank_questions (
  section_id, question_number, question_type, prompt, options, correct_answer, skill_tag, difficulty
)
SELECT
  'c1620000-0000-4000-8000-000000050300'::uuid,
  q.question_number,
  q.question_type,
  q.prompt,
  jsonb_build_object(
    'kind', COALESCE(q.options->>'kind', CASE WHEN q.part = 2 THEN 'part2_intro' ELSE 'question' END),
    'part_label', 'Part ' || q.part::text,
    'speak_time_sec', CASE q.part WHEN 1 THEN 30 WHEN 2 THEN 120 ELSE 45 END,
    'min_skip_sec', CASE WHEN q.part = 2 THEN 30 ELSE 5 END,
    'prep_sec', CASE WHEN q.part = 2 THEN 60 ELSE 0 END,
    'record_sec', CASE q.part WHEN 1 THEN 120 WHEN 2 THEN 120 ELSE 60 END,
    'video_url', q.options->>'video_url',
    'video_asset', q.options->>'video_asset'
  ),
  '',
  'speaking',
  'medium'
FROM questions q
WHERE q.mock_test_id = 'a1000000-0000-4000-8000-000000000005'
  AND q.module = 'speaking'
  AND q.part = 3;

DELETE FROM program_content_items
WHERE plan_id = (SELECT id FROM plans WHERE slug = 'speaking_skill' LIMIT 1);

INSERT INTO program_content_items (
  id, plan_id, item_type, item_id, exam_module, sort_order, is_active
)
SELECT
  ('d2100000-0000-4000-8000-' || lpad(v.sort_order::text, 12, '0'))::uuid,
  (SELECT id FROM plans WHERE slug = 'speaking_skill' LIMIT 1),
  'practice_hub',
  v.hub_id::uuid,
  'both',
  v.sort_order,
  true
FROM (VALUES
  (1, 'c1610000-0000-4000-8000-000000010100'),
  (2, 'c1610000-0000-4000-8000-000000010200'),
  (3, 'c1610000-0000-4000-8000-000000010300'),
  (4, 'c1610000-0000-4000-8000-000000020100'),
  (5, 'c1610000-0000-4000-8000-000000020200'),
  (6, 'c1610000-0000-4000-8000-000000020300'),
  (7, 'c1610000-0000-4000-8000-000000030100'),
  (8, 'c1610000-0000-4000-8000-000000030200'),
  (9, 'c1610000-0000-4000-8000-000000030300'),
  (10, 'c1610000-0000-4000-8000-000000040100'),
  (11, 'c1610000-0000-4000-8000-000000040200'),
  (12, 'c1610000-0000-4000-8000-000000040300'),
  (13, 'c1610000-0000-4000-8000-000000050100'),
  (14, 'c1610000-0000-4000-8000-000000050200'),
  (15, 'c1610000-0000-4000-8000-000000050300')
) AS v(sort_order, hub_id);

INSERT INTO program_content_items (
  id, plan_id, item_type, item_id, exam_module, sort_order, is_active
)
VALUES (
  'd2100000-0000-4000-8000-000000000100',
  (SELECT id FROM plans WHERE slug = 'speaking_skill' LIMIT 1),
  'mock_test',
  'a1000000-0000-4000-8000-000000000001',
  'both',
  100,
  true
);

UPDATE skill_full_mocks
SET mock_test_id = 'a1000000-0000-4000-8000-000000000001',
    unlock_requires_sets = 15
WHERE skill = 'speaking';

UPDATE plans SET is_active = true WHERE slug = 'speaking_skill';
