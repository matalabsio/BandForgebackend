-- Keep only Society & Culture speaking questions (55 rows on a100… mocks).
-- Remove legacy Mock 1 / Mock 2 speaking prompts so video attach stays clean.

-- Drop student responses that pointed at the old M01/M02 speaking questions.
DELETE FROM speaking_responses
WHERE question_id IN (
  SELECT id
  FROM questions
  WHERE module = 'speaking'
    AND mock_test_id IN (
      'a0000000-0000-4000-8000-000000000001',
      'a0000000-0000-4000-8000-000000000002'
    )
);

DELETE FROM questions
WHERE module = 'speaking'
  AND mock_test_id IN (
    'a0000000-0000-4000-8000-000000000001',
    'a0000000-0000-4000-8000-000000000002'
  );

-- Academic M01/M02 no longer have speaking content.
UPDATE mock_test_modules
SET is_enabled = false
WHERE module = 'speaking'
  AND mock_test_id IN (
    'a0000000-0000-4000-8000-000000000001',
    'a0000000-0000-4000-8000-000000000002'
  );

-- Also drop diagnostic speaking (separate seed); inventory must be SC-only.
DELETE FROM speaking_responses
WHERE question_id IN (
  SELECT id
  FROM questions
  WHERE module = 'speaking'
    AND mock_test_id = 'd0000000-0000-4000-8000-000000000001'
);

DELETE FROM questions
WHERE module = 'speaking'
  AND mock_test_id = 'd0000000-0000-4000-8000-000000000001';

UPDATE mock_test_modules
SET is_enabled = false
WHERE module = 'speaking'
  AND mock_test_id = 'd0000000-0000-4000-8000-000000000001';
