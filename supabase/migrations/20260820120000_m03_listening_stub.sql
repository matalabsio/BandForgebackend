-- Academic Mock 3 (M03 / Test 3) — unpublished until Reading/Writing exist.
-- Listening questions are seeded separately (m03_listening_sN_seed.sql).

INSERT INTO mock_tests (
  id, title, description, status, is_published, catalog_number,
  listening_parts, reading_passages, writing_tasks, is_diagnostic
)
VALUES (
  'a0000000-0000-4000-8000-000000000003',
  'IELTS Academic Mock 3',
  'Listening (4 parts, 30 min). Reading, Writing, and Speaking coming soon.',
  'draft',
  false,
  3,
  4,
  0,
  0,
  false
)
ON CONFLICT (id) DO UPDATE SET
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  status = EXCLUDED.status,
  is_published = EXCLUDED.is_published,
  catalog_number = EXCLUDED.catalog_number,
  listening_parts = EXCLUDED.listening_parts,
  reading_passages = EXCLUDED.reading_passages,
  writing_tasks = EXCLUDED.writing_tasks,
  is_diagnostic = EXCLUDED.is_diagnostic;

INSERT INTO mock_test_modules (mock_test_id, module, sequence_order, duration_minutes, is_enabled)
VALUES
  ('a0000000-0000-4000-8000-000000000003', 'listening', 1, 30, true),
  ('a0000000-0000-4000-8000-000000000003', 'reading', 2, 30, false),
  ('a0000000-0000-4000-8000-000000000003', 'writing', 3, 60, false),
  ('a0000000-0000-4000-8000-000000000003', 'speaking', 4, 14, false)
ON CONFLICT (mock_test_id, module) DO UPDATE SET
  sequence_order = EXCLUDED.sequence_order,
  duration_minutes = EXCLUDED.duration_minutes,
  is_enabled = EXCLUDED.is_enabled;
