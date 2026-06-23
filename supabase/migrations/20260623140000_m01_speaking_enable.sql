-- Mock Test 1: enable Speaking (Part 1) alongside existing L/R/W modules.

UPDATE mock_test_modules
SET is_enabled = true,
    duration_minutes = 14
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001'
  AND module = 'speaking';

UPDATE mock_tests
SET description = 'Listening (4 parts · 30 min) → Reading (2 passages · 30 min) → Writing (Tasks 1-2 · 60 min) → Speaking Part 1 (human-reviewed within 24h).'
WHERE id = 'a0000000-0000-4000-8000-000000000001';

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
VALUES (
  'c1000000-0000-4000-8000-000000000001',
  'a0000000-0000-4000-8000-000000000001',
  'speaking',
  'speaking_part1',
  1,
  1,
  E'Part 1 — Introduction and interview\n\nPlease record your answer (about 1–2 minutes).\n\nTell me about yourself. In your response, please cover:\n• Who you are and what you do now\n• Why you are taking the IELTS exam\n• Where you plan to go (study, work, or migration)\n• Your main goal or purpose for taking the test',
  '{"duration_hint_sec": 120, "part_label": "Part 1"}'::jsonb
)
ON CONFLICT (id) DO UPDATE SET
  prompt = EXCLUDED.prompt,
  options = EXCLUDED.options,
  question_type = EXCLUDED.question_type,
  part = EXCLUDED.part;
