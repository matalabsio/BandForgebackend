-- Multi-mock orchestration: parent mock_attempts + module sequence config

-- ---------------------------------------------------------------------------
-- MOCK_ATTEMPTS — full IELTS exam journey per user
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mock_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  mock_test_id uuid NOT NULL REFERENCES mock_tests(id) ON DELETE CASCADE,
  status varchar(20) NOT NULL DEFAULT 'in_progress',
  current_module varchar(20),
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  CONSTRAINT mock_attempts_status_check CHECK (
    status IN ('in_progress', 'completed', 'abandoned')
  ),
  CONSTRAINT mock_attempts_current_module_check CHECK (
    current_module IS NULL OR current_module IN ('reading', 'listening', 'writing', 'speaking')
  )
);

CREATE INDEX IF NOT EXISTS idx_mock_attempts_user_id ON mock_attempts (user_id);
CREATE INDEX IF NOT EXISTS idx_mock_attempts_mock_test_id ON mock_attempts (mock_test_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mock_attempts_user_mock_in_progress
  ON mock_attempts (user_id, mock_test_id)
  WHERE status = 'in_progress';

COMMENT ON TABLE mock_attempts IS 'Top-level IELTS mock exam session; groups module test_attempts';

-- ---------------------------------------------------------------------------
-- MOCK_TEST_MODULES — sequential unlock order per published mock
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mock_test_modules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  mock_test_id uuid NOT NULL REFERENCES mock_tests(id) ON DELETE CASCADE,
  module varchar(20) NOT NULL,
  sequence_order smallint NOT NULL,
  duration_minutes integer NOT NULL DEFAULT 30,
  is_enabled boolean NOT NULL DEFAULT true,
  CONSTRAINT mock_test_modules_module_check CHECK (
    module IN ('reading', 'listening', 'writing', 'speaking')
  ),
  CONSTRAINT mock_test_modules_mock_module_unique UNIQUE (mock_test_id, module),
  CONSTRAINT mock_test_modules_mock_order_unique UNIQUE (mock_test_id, sequence_order)
);

CREATE INDEX IF NOT EXISTS idx_mock_test_modules_mock_test_id
  ON mock_test_modules (mock_test_id);

COMMENT ON TABLE mock_test_modules IS 'Per-mock module order and timing for orchestrator';

-- ---------------------------------------------------------------------------
-- TEST_ATTEMPTS — link module attempts to parent mock_attempt
-- ---------------------------------------------------------------------------
ALTER TABLE test_attempts
  ADD COLUMN IF NOT EXISTS mock_attempt_id uuid REFERENCES mock_attempts(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_test_attempts_mock_attempt_id
  ON test_attempts (mock_attempt_id);

CREATE INDEX IF NOT EXISTS idx_test_attempts_mock_attempt_module
  ON test_attempts (mock_attempt_id, module);

-- Extend questions.part for reading passages (1..3) — listening stays 1..4
ALTER TABLE questions DROP CONSTRAINT IF EXISTS questions_part_check;
ALTER TABLE questions
  ADD CONSTRAINT questions_part_check
  CHECK (part IS NULL OR (part BETWEEN 1 AND 4));
