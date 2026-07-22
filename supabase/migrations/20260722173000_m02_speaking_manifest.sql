-- Enable Speaking on Mock Test 2 with a Test-1-style Parts 1–3 manifest
-- (same flow: record → upload → AI estimate / human review).

UPDATE public.mock_test_modules
SET is_enabled = true,
    duration_minutes = 14
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000002'
  AND module = 'speaking';

INSERT INTO questions (
  id,
  mock_test_id,
  module,
  question_type,
  question_number,
  part,
  prompt,
  options
)
VALUES
  (
    'c2000000-0000-4000-8000-000000000001',
    'a0000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part1',
    1,
    1,
    'Let''s talk about your hometown. Where are you from?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1"}'::jsonb
  ),
  (
    'c2000000-0000-4000-8000-000000000002',
    'a0000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part1',
    2,
    1,
    'What do you like most about living there?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1"}'::jsonb
  ),
  (
    'c2000000-0000-4000-8000-000000000003',
    'a0000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part1',
    3,
    1,
    'Has your hometown changed much in recent years?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1"}'::jsonb
  ),
  (
    'c2000000-0000-4000-8000-000000000004',
    'a0000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part1',
    4,
    1,
    'Would you recommend your hometown to a visitor?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1"}'::jsonb
  ),
  (
    'c2000000-0000-4000-8000-000000000005',
    'a0000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part2',
    1,
    2,
    E'Describe a skill you learned that you are proud of.\n\nYou should say:\n• what the skill was\n• when and how you learned it\n• why you are proud of it\n\nand explain how this skill has helped you.',
    '{"kind":"part2_intro","prep_sec":60,"record_sec":120,"duration_hint_sec":120,"part_label":"Part 2"}'::jsonb
  ),
  (
    'c2000000-0000-4000-8000-000000000006',
    'a0000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part3',
    1,
    3,
    'Why do you think continuous learning is important?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3"}'::jsonb
  ),
  (
    'c2000000-0000-4000-8000-000000000007',
    'a0000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part3',
    2,
    3,
    'How has technology changed the way people learn new skills?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3"}'::jsonb
  ),
  (
    'c2000000-0000-4000-8000-000000000008',
    'a0000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part3',
    3,
    3,
    'Do you think schools prepare students well for real-world skills?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3"}'::jsonb
  )
ON CONFLICT (id) DO UPDATE SET
  mock_test_id = EXCLUDED.mock_test_id,
  question_type = EXCLUDED.question_type,
  question_number = EXCLUDED.question_number,
  part = EXCLUDED.part,
  prompt = EXCLUDED.prompt,
  options = EXCLUDED.options;
