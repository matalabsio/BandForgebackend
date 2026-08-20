-- Academic Mock 5 (M05 / Test 5) — unpublished; Writing T1 only (T2 pending).
-- Question rows seeded separately (m05_*_seed.sql).

INSERT INTO mock_tests (
  id, title, description, status, is_published, catalog_number,
  listening_parts, reading_passages, writing_tasks, is_diagnostic
)
VALUES (
  'a0000000-0000-4000-8000-000000000005',
  'IELTS Academic Mock 5',
  'Listening (4 parts), Reading (3 passages), Writing (1 task). Speaking coming soon.',
  'draft',
  false,
  5,
  4,
  3,
  1,
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
  ('a0000000-0000-4000-8000-000000000005', 'listening', 1, 30, true),
  ('a0000000-0000-4000-8000-000000000005', 'reading', 2, 30, true),
  ('a0000000-0000-4000-8000-000000000005', 'writing', 3, 60, true),
  ('a0000000-0000-4000-8000-000000000005', 'speaking', 4, 14, false)
ON CONFLICT (mock_test_id, module) DO UPDATE SET
  sequence_order = EXCLUDED.sequence_order,
  duration_minutes = EXCLUDED.duration_minutes,
  is_enabled = EXCLUDED.is_enabled;
