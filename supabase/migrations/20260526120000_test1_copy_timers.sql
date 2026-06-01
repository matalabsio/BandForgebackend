-- Test 1 (M01): UI-aligned description and 20+20 minute section timers

UPDATE mock_tests
SET
  title = 'IELTS Academic Mock 1',
  description = 'Reading (13 questions) → Listening (10 questions). Writing and Speaking coming soon.',
  is_published = true
WHERE id = 'a0000000-0000-4000-8000-000000000001';

UPDATE mock_test_modules
SET duration_minutes = 20
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001'
  AND module IN ('reading', 'listening');
