-- Academic Mock 4 — enable Reading (3 passages) + Writing (2 tasks); still unpublished.
-- Question rows seeded separately (m04_reading_pN_seed.sql, m04_writing_seed.sql).

UPDATE mock_tests
SET
  description = 'Listening (4 parts), Reading (3 passages), Writing (2 tasks). Speaking coming soon.',
  reading_passages = 3,
  writing_tasks = 2
WHERE id = 'a0000000-0000-4000-8000-000000000004';

UPDATE mock_test_modules
SET is_enabled = true
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000004'
  AND module IN ('reading', 'writing');
