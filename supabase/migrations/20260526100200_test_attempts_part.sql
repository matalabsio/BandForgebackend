-- Section within a module (listening part 1-4, reading passage 1-3)

ALTER TABLE test_attempts
  ADD COLUMN IF NOT EXISTS part smallint;

CREATE INDEX IF NOT EXISTS idx_test_attempts_user_mock_module_part_in_progress
  ON test_attempts (user_id, mock_test_id, module, part)
  WHERE status = 'in_progress';

COMMENT ON COLUMN test_attempts.part IS
  'Sub-section: listening part 1-4 or reading passage 1-3; NULL for whole-module attempts';
