-- Admin-created mocks seeded speaking with is_enabled=false, so the student
-- hub showed L · R · W only. Align with Test 1 / Test 2 and list Speaking.

UPDATE mock_test_modules
SET is_enabled = true,
    duration_minutes = COALESCE(duration_minutes, 14)
WHERE module = 'speaking'
  AND is_enabled = false;
