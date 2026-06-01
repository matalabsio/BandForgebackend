-- Test 1: full listening (4 parts) uses 30 minutes; update catalog copy

UPDATE mock_tests
SET description = 'Reading (13 questions) → Listening (4 parts, 40 questions). Writing and Speaking coming soon.'
WHERE id = 'a0000000-0000-4000-8000-000000000001';

UPDATE mock_test_modules
SET duration_minutes = 30
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001'
  AND module = 'listening';

UPDATE mock_test_modules
SET duration_minutes = 20
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001'
  AND module = 'reading';
