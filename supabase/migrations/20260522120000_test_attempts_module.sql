-- Day 2: track which module (reading/listening/...) an attempt is for

ALTER TABLE test_attempts
  ADD COLUMN IF NOT EXISTS module varchar(20);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'test_attempts_module_check'
  ) THEN
    ALTER TABLE test_attempts
      ADD CONSTRAINT test_attempts_module_check
      CHECK (module IS NULL OR module IN ('reading', 'listening', 'writing', 'speaking'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_test_attempts_user_mock_module
  ON test_attempts (user_id, mock_test_id, module)
  WHERE status = 'in_progress';
