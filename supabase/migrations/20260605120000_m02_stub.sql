-- Academic Mock 2 (M02 / Test 2) — catalog stub; question content seeded separately.

INSERT INTO mock_tests (id, title, description, is_published)
VALUES (
  'a0000000-0000-4000-8000-000000000002',
  'IELTS Academic Mock 2',
  'Listening (4 parts, 40 questions, 30 min) → Reading (2 passages, 30 min) → Writing (2 tasks, 60 min).',
  true
)
ON CONFLICT (id) DO UPDATE SET
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  is_published = EXCLUDED.is_published;

INSERT INTO mock_test_modules (mock_test_id, module, sequence_order, duration_minutes, is_enabled)
VALUES
  ('a0000000-0000-4000-8000-000000000002', 'listening', 1, 30, true),
  ('a0000000-0000-4000-8000-000000000002', 'reading', 2, 30, true),
  ('a0000000-0000-4000-8000-000000000002', 'writing', 3, 60, true),
  ('a0000000-0000-4000-8000-000000000002', 'speaking', 4, 14, false)
ON CONFLICT (mock_test_id, module) DO UPDATE SET
  sequence_order = EXCLUDED.sequence_order,
  duration_minutes = EXCLUDED.duration_minutes,
  is_enabled = EXCLUDED.is_enabled;
