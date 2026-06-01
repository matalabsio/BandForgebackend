-- Test 1: swap module order (listening first) without unique constraint clash

UPDATE mock_test_modules
SET sequence_order = CASE module
  WHEN 'listening' THEN 10
  WHEN 'reading' THEN 20
  ELSE sequence_order
END
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001'
  AND module IN ('listening', 'reading');

UPDATE mock_test_modules
SET
  sequence_order = CASE module
    WHEN 'listening' THEN 1
    WHEN 'reading' THEN 2
    ELSE sequence_order
  END,
  duration_minutes = CASE module
    WHEN 'listening' THEN 30
    WHEN 'reading' THEN 30
    ELSE duration_minutes
  END
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001'
  AND module IN ('listening', 'reading');

UPDATE mock_tests
SET description = 'Listening (4 parts · 40 questions · 30 min) → Reading (4 passages · 30 min). Writing and Speaking coming soon.'
WHERE id = 'a0000000-0000-4000-8000-000000000001';
