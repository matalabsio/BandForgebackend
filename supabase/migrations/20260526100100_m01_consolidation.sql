-- Consolidate founder section mocks into Academic Mock 1 (M01)

-- M01 UUID
-- a0000000-0000-4000-8000-000000000001

INSERT INTO mock_tests (id, title, description, is_published)
VALUES (
  'a0000000-0000-4000-8000-000000000001',
  'IELTS Academic Mock 1',
  'Listening (4 parts, 40 questions, 30 min) → Reading (4 passages, 30 min). Writing and Speaking coming soon.',
  true
)
ON CONFLICT (id) DO UPDATE SET
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  is_published = EXCLUDED.is_published;

INSERT INTO mock_test_modules (mock_test_id, module, sequence_order, duration_minutes, is_enabled)
VALUES
  ('a0000000-0000-4000-8000-000000000001', 'listening', 1, 30, true),
  ('a0000000-0000-4000-8000-000000000001', 'reading', 2, 30, true),
  ('a0000000-0000-4000-8000-000000000001', 'writing', 3, 60, false),
  ('a0000000-0000-4000-8000-000000000001', 'speaking', 4, 14, false)
ON CONFLICT (mock_test_id, module) DO UPDATE SET
  sequence_order = EXCLUDED.sequence_order,
  duration_minutes = EXCLUDED.duration_minutes,
  is_enabled = EXCLUDED.is_enabled;

-- Listening Part 1 (Greenfield)
UPDATE questions
SET
  mock_test_id = 'a0000000-0000-4000-8000-000000000001',
  part = 1,
  audio_url = 'listening/m01/part-1/full.mp3'
WHERE mock_test_id = 'd0000000-0000-4000-8000-000000000001'
  AND module = 'listening';

-- Listening Part 2
UPDATE questions
SET
  mock_test_id = 'a0000000-0000-4000-8000-000000000001',
  part = 2,
  audio_url = 'listening/m01/part-2/full.mp3'
WHERE mock_test_id = 'e0000000-0000-4000-8000-000000000002'
  AND module = 'listening';

-- Listening Part 3
UPDATE questions
SET
  mock_test_id = 'a0000000-0000-4000-8000-000000000001',
  part = 3,
  audio_url = 'listening/m01/part-3/full.mp3'
WHERE mock_test_id = 'e0000000-0000-4000-8000-000000000003'
  AND module = 'listening';

-- Listening Part 4
UPDATE questions
SET
  mock_test_id = 'a0000000-0000-4000-8000-000000000001',
  part = 4,
  audio_url = 'listening/m01/part-4/full.mp3'
WHERE mock_test_id = 'e0000000-0000-4000-8000-000000000004'
  AND module = 'listening';

-- Reading Passage 1 (Task 2)
UPDATE questions
SET
  mock_test_id = 'a0000000-0000-4000-8000-000000000001',
  part = 1
WHERE mock_test_id = 'b0000000-0000-4000-8000-000000000002'
  AND module = 'reading';

-- Reading Passage 2 (Task 3)
UPDATE questions
SET
  mock_test_id = 'a0000000-0000-4000-8000-000000000001',
  part = 2
WHERE mock_test_id = 'b0000000-0000-4000-8000-000000000003'
  AND module = 'reading';

-- Remove day-2 dev placeholder rows (no part) superseded by founder content
DELETE FROM questions
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001'
  AND part IS NULL;

-- Repoint historical module attempts to M01 (scores preserved)
UPDATE test_attempts
SET mock_test_id = 'a0000000-0000-4000-8000-000000000001'
WHERE mock_test_id IN (
  'd0000000-0000-4000-8000-000000000001',
  'e0000000-0000-4000-8000-000000000002',
  'e0000000-0000-4000-8000-000000000003',
  'e0000000-0000-4000-8000-000000000004',
  'b0000000-0000-4000-8000-000000000002',
  'b0000000-0000-4000-8000-000000000003'
);

-- Unpublish legacy section-only catalog rows
UPDATE mock_tests SET is_published = false
WHERE id IN (
  'd0000000-0000-4000-8000-000000000001',
  'e0000000-0000-4000-8000-000000000002',
  'e0000000-0000-4000-8000-000000000003',
  'e0000000-0000-4000-8000-000000000004',
  'b0000000-0000-4000-8000-000000000002',
  'b0000000-0000-4000-8000-000000000003',
  'b0000000-0000-4000-8000-000000000001'
);
