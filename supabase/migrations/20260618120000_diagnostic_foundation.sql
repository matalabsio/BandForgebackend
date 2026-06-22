-- Diagnostic product foundation: separate mock test (not in catalog), placeholder Q&A.

ALTER TABLE mock_tests
  ADD COLUMN IF NOT EXISTS is_diagnostic boolean NOT NULL DEFAULT false;

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users
  ADD CONSTRAINT users_role_check
  CHECK (role IN ('student', 'admin', 'super_admin', 'guest'));

INSERT INTO mock_tests (
  id, title, description, is_published, status, catalog_number,
  listening_parts, reading_passages, writing_tasks, is_diagnostic
)
VALUES (
  'd0000000-0000-4000-8000-000000000001',
  'BandForge Free Diagnostic',
  'Short diagnostic: Listening (10 Q) → Reading (10 Q) → Writing (1 task).',
  true,
  'published',
  NULL,
  1,
  1,
  1,
  true
)
ON CONFLICT (id) DO UPDATE SET
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  is_published = EXCLUDED.is_published,
  status = EXCLUDED.status,
  catalog_number = EXCLUDED.catalog_number,
  listening_parts = EXCLUDED.listening_parts,
  reading_passages = EXCLUDED.reading_passages,
  writing_tasks = EXCLUDED.writing_tasks,
  is_diagnostic = EXCLUDED.is_diagnostic;

INSERT INTO mock_test_modules (mock_test_id, module, sequence_order, duration_minutes, is_enabled)
VALUES
  ('d0000000-0000-4000-8000-000000000001', 'listening', 1, 15, true),
  ('d0000000-0000-4000-8000-000000000001', 'reading', 2, 20, true),
  ('d0000000-0000-4000-8000-000000000001', 'writing', 3, 20, true),
  ('d0000000-0000-4000-8000-000000000001', 'speaking', 4, 14, false)
ON CONFLICT (mock_test_id, module) DO UPDATE SET
  sequence_order = EXCLUDED.sequence_order,
  duration_minutes = EXCLUDED.duration_minutes,
  is_enabled = EXCLUDED.is_enabled;

-- Listening: 10 placeholder questions (part 1)
DELETE FROM answers WHERE question_id IN (
  SELECT id FROM questions
  WHERE mock_test_id = 'd0000000-0000-4000-8000-000000000001'
    AND module = 'listening' AND part = 1
);
DELETE FROM questions
WHERE mock_test_id = 'd0000000-0000-4000-8000-000000000001'
  AND module = 'listening' AND part = 1;

INSERT INTO questions (
  mock_test_id, module, part, question_type, question_number, prompt,
  passage_text, audio_url, options, correct_answer, skill_tag
) VALUES
('d0000000-0000-4000-8000-000000000001', 'listening', 1, 'multiple_choice', 1,
 'Diagnostic placeholder Q1: What is the caller''s main reason for phoning?',
 E'Diagnostic Listening — Placeholder Section\n\nSTAFF: BandForge Learning Centre, good morning.\nCALLER: Hello, I''d like some information about your IELTS preparation courses.\nSTAFF: Certainly. Are you preparing for Academic or General Training?\nCALLER: Academic, please. I need a band score of 7 for my university application.\nSTAFF: We offer a free diagnostic test that shows your current level across listening, reading, and writing.\nCALLER: That sounds helpful. How long does the diagnostic take?\nSTAFF: About forty-five minutes. You can start online without creating an account.\nCALLER: Perfect. I''ll try it today. My name is Sarah Chen.\nSTAFF: Thank you, Sarah. Good luck with your preparation.',
 'listening/diagnostic/part-1/full.mp3',
 '[{"label":"A","text":"To book a speaking test"},{"label":"B","text":"To ask about IELTS courses"},{"label":"C","text":"To cancel a membership"}]'::jsonb,
 'B', 'gist'),
('d0000000-0000-4000-8000-000000000001', 'listening', 1, 'multiple_choice', 2,
 'Diagnostic placeholder Q2: Which IELTS module does the caller need?',
 NULL, 'listening/diagnostic/part-1/full.mp3',
 '[{"label":"A","text":"General Training"},{"label":"B","text":"Academic"},{"label":"C","text":"Both"}]'::jsonb,
 'B', 'detail'),
('d0000000-0000-4000-8000-000000000001', 'listening', 1, 'multiple_choice', 3,
 'Diagnostic placeholder Q3: What band score does the caller need?',
 NULL, 'listening/diagnostic/part-1/full.mp3',
 '[{"label":"A","text":"6.5"},{"label":"B","text":"7"},{"label":"C","text":"7.5"}]'::jsonb,
 'B', 'detail'),
('d0000000-0000-4000-8000-000000000001', 'listening', 1, 'multiple_choice', 4,
 'Diagnostic placeholder Q4: How long does the diagnostic take?',
 NULL, 'listening/diagnostic/part-1/full.mp3',
 '[{"label":"A","text":"About 30 minutes"},{"label":"B","text":"About 45 minutes"},{"label":"C","text":"About 90 minutes"}]'::jsonb,
 'B', 'detail'),
('d0000000-0000-4000-8000-000000000001', 'listening', 1, 'multiple_choice', 5,
 'Diagnostic placeholder Q5: Can the caller start without an account?',
 NULL, 'listening/diagnostic/part-1/full.mp3',
 '[{"label":"A","text":"Yes"},{"label":"B","text":"No"},{"label":"C","text":"Only with a referral"}]'::jsonb,
 'A', 'detail'),
('d0000000-0000-4000-8000-000000000001', 'listening', 1, 'sentence_completion', 6,
 'Diagnostic placeholder Q6: Caller surname',
 NULL, 'listening/diagnostic/part-1/full.mp3', NULL, 'Chen', 'detail'),
('d0000000-0000-4000-8000-000000000001', 'listening', 1, 'sentence_completion', 7,
 'Diagnostic placeholder Q7: Caller first name',
 NULL, 'listening/diagnostic/part-1/full.mp3', NULL, 'Sarah', 'detail'),
('d0000000-0000-4000-8000-000000000001', 'listening', 1, 'sentence_completion', 8,
 'Diagnostic placeholder Q8: Centre name',
 NULL, 'listening/diagnostic/part-1/full.mp3', NULL, 'BandForge', 'detail'),
('d0000000-0000-4000-8000-000000000001', 'listening', 1, 'sentence_completion', 9,
 'Diagnostic placeholder Q9: Test type offered free',
 NULL, 'listening/diagnostic/part-1/full.mp3', NULL, 'diagnostic', 'detail'),
('d0000000-0000-4000-8000-000000000001', 'listening', 1, 'sentence_completion', 10,
 'Diagnostic placeholder Q10: Modules in diagnostic (count)',
 NULL, 'listening/diagnostic/part-1/full.mp3', NULL, 'three/3', 'detail');

-- Reading: 10 placeholder questions (passage 1)
DELETE FROM answers WHERE question_id IN (
  SELECT id FROM questions
  WHERE mock_test_id = 'd0000000-0000-4000-8000-000000000001'
    AND module = 'reading' AND part = 1
);
DELETE FROM questions
WHERE mock_test_id = 'd0000000-0000-4000-8000-000000000001'
  AND module = 'reading' AND part = 1;

INSERT INTO questions (
  mock_test_id, module, question_type, question_number, part, prompt,
  passage_text, options, correct_answer, skill_tag
) VALUES
('d0000000-0000-4000-8000-000000000001', 'reading', 'tfng', 1, 1,
 'Diagnostic placeholder R1: Community gardens are sometimes supported by local councils.',
 E'Diagnostic Reading — Placeholder Passage\n\nUrban Community Gardens\n\nA    Across many cities, unused plots of land have been converted into community gardens where residents grow vegetables and flowers together. These projects began as informal neighbourhood efforts but are now often supported by local councils that provide water access and basic tools.\n\nB    Research suggests that participants report lower stress and stronger social ties after joining a garden. Children who help with planting also show more interest in fresh food, though scientists caution that long-term health effects are still being studied.\n\nC    Not every garden succeeds. Sites near busy roads may struggle with pollution, and some groups disband when founding volunteers move away. Even so, the movement continues to spread as cities look for low-cost ways to improve green space.',
 '[{"label":"TRUE","text":"TRUE"},{"label":"FALSE","text":"FALSE"},{"label":"NOT GIVEN","text":"NOT GIVEN"}]'::jsonb,
 'TRUE', 'tfng'),
('d0000000-0000-4000-8000-000000000001', 'reading', 'tfng', 2, 1,
 'Diagnostic placeholder R2: All community gardens near busy roads fail within one year.',
 NULL,
 '[{"label":"TRUE","text":"TRUE"},{"label":"FALSE","text":"FALSE"},{"label":"NOT GIVEN","text":"NOT GIVEN"}]'::jsonb,
 'FALSE', 'tfng'),
('d0000000-0000-4000-8000-000000000001', 'reading', 'tfng', 3, 1,
 'Diagnostic placeholder R3: Every child who joins a garden eats more vegetables at home.',
 NULL,
 '[{"label":"TRUE","text":"TRUE"},{"label":"FALSE","text":"FALSE"},{"label":"NOT GIVEN","text":"NOT GIVEN"}]'::jsonb,
 'NOT GIVEN', 'tfng'),
('d0000000-0000-4000-8000-000000000001', 'reading', 'tfng', 4, 1,
 'Diagnostic placeholder R4: Participants often report lower stress after joining.',
 NULL,
 '[{"label":"TRUE","text":"TRUE"},{"label":"FALSE","text":"FALSE"},{"label":"NOT GIVEN","text":"NOT GIVEN"}]'::jsonb,
 'TRUE', 'tfng'),
('d0000000-0000-4000-8000-000000000001', 'reading', 'tfng', 5, 1,
 'Diagnostic placeholder R5: Gardens began as informal neighbourhood efforts.',
 NULL,
 '[{"label":"TRUE","text":"TRUE"},{"label":"FALSE","text":"FALSE"},{"label":"NOT GIVEN","text":"NOT GIVEN"}]'::jsonb,
 'TRUE', 'tfng'),
('d0000000-0000-4000-8000-000000000001', 'reading', 'sentence_completion', 6, 1,
 'Diagnostic placeholder R6: Councils may provide water access and basic ______.',
 NULL, NULL, 'tools', 'sentence_completion'),
('d0000000-0000-4000-8000-000000000001', 'reading', 'sentence_completion', 7, 1,
 'Diagnostic placeholder R7: Some groups disband when founding ______ move away.',
 NULL, NULL, 'volunteers', 'sentence_completion'),
('d0000000-0000-4000-8000-000000000001', 'reading', 'sentence_completion', 8, 1,
 'Diagnostic placeholder R8: Cities look for low-cost ways to improve green ______.',
 NULL, NULL, 'space', 'sentence_completion'),
('d0000000-0000-4000-8000-000000000001', 'reading', 'sentence_completion', 9, 1,
 'Diagnostic placeholder R9: Children show more interest in fresh ______.',
 NULL, NULL, 'food', 'sentence_completion'),
('d0000000-0000-4000-8000-000000000001', 'reading', 'sentence_completion', 10, 1,
 'Diagnostic placeholder R10: Long-term health effects are still being ______.',
 NULL, NULL, 'studied', 'sentence_completion');

-- Writing: 1 placeholder task
DELETE FROM questions
WHERE mock_test_id = 'd0000000-0000-4000-8000-000000000001'
  AND module = 'writing';

INSERT INTO questions (
  mock_test_id, module, question_type, question_number, part, prompt, options
)
VALUES (
  'd0000000-0000-4000-8000-000000000001',
  'writing',
  'task1_academic',
  1,
  1,
  $prompt$You should spend about 20 minutes on this task.

The chart below shows illustrative data for a BandForge diagnostic placeholder.

Summarise the information by selecting and reporting the main features, and make comparisons where relevant.

Write at least 150 words.$prompt$,
  '{"min_words": 150, "title": "WRITING TASK 1 — Diagnostic Placeholder", "difficulty": "Diagnostic"}'::jsonb
);
