-- Day 2 dev seed — run in Supabase SQL Editor after all migrations (including 20260522120000_test_attempts_module.sql)
-- Idempotent: safe to re-run (deletes prior seed questions for this mock test).

DELETE FROM answers WHERE attempt_id IN (
  SELECT id FROM test_attempts WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001'
);
DELETE FROM test_attempts WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001';
DELETE FROM questions WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001';

-- Published mock test
INSERT INTO mock_tests (id, title, description, is_published)
VALUES (
  'a0000000-0000-4000-8000-000000000001',
  'Day 2 Dev — Reading + Listening',
  'Postman smoke test seed',
  true
)
ON CONFLICT (id) DO UPDATE SET is_published = true, title = EXCLUDED.title;

-- Reading (shared passage)
INSERT INTO questions (
  mock_test_id, module, question_type, question_number, prompt,
  passage_text, options, correct_answer, skill_tag
) VALUES
(
  'a0000000-0000-4000-8000-000000000001', 'reading', 'mcq', 1,
  'What is the main idea of the passage?',
  'The passage discusses renewable energy adoption in urban areas over the last decade.',
  '[{"label":"A","text":"Cities reject solar power"},{"label":"B","text":"Urban renewable use has grown"},{"label":"C","text":"Oil prices are stable"},{"label":"D","text":"Rural areas lead adoption"}]'::jsonb,
  'B', 'main_idea'
),
(
  'a0000000-0000-4000-8000-000000000001', 'reading', 'mcq', 2,
  'According to the passage, which trend is mentioned?',
  'The passage discusses renewable energy adoption in urban areas over the last decade.',
  '[{"label":"A","text":"Declining wind farms"},{"label":"B","text":"Growth in urban renewables"},{"label":"C","text":"Ban on electric buses"},{"label":"D","text":"No policy changes"}]'::jsonb,
  'B', 'inference'
),
(
  'a0000000-0000-4000-8000-000000000001', 'reading', 'tfng', 3,
  'The passage states that adoption has decreased.',
  'The passage discusses renewable energy adoption in urban areas over the last decade.',
  NULL,
  'FALSE', 'tfng'
)
;

-- Listening (audio_url = R2 object key — upload a file or use health-check path for presign test)
INSERT INTO questions (
  mock_test_id, module, question_type, question_number, prompt,
  audio_url, options, correct_answer, skill_tag
) VALUES
(
  'a0000000-0000-4000-8000-000000000001', 'listening', 'mcq', 1,
  'What is the speaker''s purpose?',
  'listening/day2-dev/section-1.mp3',
  '[{"label":"A","text":"To book a room"},{"label":"B","text":"To cancel a tour"},{"label":"C","text":"To ask directions"},{"label":"D","text":"To buy tickets"}]'::jsonb,
  'A', 'main_idea'
),
(
  'a0000000-0000-4000-8000-000000000001', 'listening', 'mcq', 2,
  'How many nights does the speaker want?',
  'listening/day2-dev/section-1.mp3',
  '[{"label":"A","text":"One"},{"label":"B","text":"Two"},{"label":"C","text":"Three"},{"label":"D","text":"Four"}]'::jsonb,
  'B', 'detail'
);

-- Postman: mock_test_id = a0000000-0000-4000-8000-000000000001
