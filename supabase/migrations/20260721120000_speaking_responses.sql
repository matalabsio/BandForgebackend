-- Durable, response-level Speaking uploads and a frozen per-attempt manifest.

ALTER TABLE test_attempts
  ADD COLUMN IF NOT EXISTS speaking_manifest jsonb;

ALTER TABLE test_attempts
  ADD COLUMN IF NOT EXISTS speaking_manifest_hash varchar(64);

CREATE UNIQUE INDEX IF NOT EXISTS idx_speaking_attempts_one_in_progress
  ON test_attempts (
    user_id,
    mock_test_id,
    part,
    COALESCE(mock_attempt_id, '00000000-0000-0000-0000-000000000000'::uuid)
  )
  WHERE module = 'speaking' AND status = 'in_progress';

CREATE TABLE IF NOT EXISTS speaking_responses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_id uuid NOT NULL REFERENCES test_attempts(id) ON DELETE CASCADE,
  question_id uuid NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
  part smallint NOT NULL,
  sequence_number smallint NOT NULL,
  audio_url text NOT NULL,
  content_type varchar(100) NOT NULL,
  duration_sec integer NOT NULL,
  size_bytes integer NOT NULL,
  content_sha256 varchar(64) NOT NULL,
  status varchar(20) NOT NULL DEFAULT 'uploaded',
  transcript text,
  ai_result jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT speaking_responses_part_check CHECK (part BETWEEN 1 AND 3),
  CONSTRAINT speaking_responses_sequence_check CHECK (sequence_number > 0),
  CONSTRAINT speaking_responses_duration_check CHECK (duration_sec >= 5),
  CONSTRAINT speaking_responses_size_check CHECK (size_bytes >= 2000),
  CONSTRAINT speaking_responses_sha256_check CHECK (
    content_sha256 ~ '^[0-9a-f]{64}$'
  ),
  CONSTRAINT speaking_responses_status_check CHECK (
    status IN ('uploaded', 'processing', 'processed', 'failed')
  ),
  CONSTRAINT speaking_responses_attempt_question_unique
    UNIQUE (attempt_id, question_id),
  CONSTRAINT speaking_responses_attempt_sequence_unique
    UNIQUE (attempt_id, sequence_number)
);

CREATE INDEX IF NOT EXISTS idx_speaking_responses_attempt
  ON speaking_responses (attempt_id, sequence_number);

ALTER TABLE speaking_responses ENABLE ROW LEVEL SECURITY;

CREATE POLICY speaking_responses_select_own ON speaking_responses
  FOR SELECT
  TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM test_attempts
      WHERE test_attempts.id = speaking_responses.attempt_id
        AND test_attempts.user_id = auth.uid()
    )
  );

-- No client INSERT/UPDATE/DELETE policies. The API validates the frozen
-- manifest and writes with service_role; authenticated clients may only read
-- their own response metadata.

COMMENT ON TABLE speaking_responses IS
  'One durable audio response per server-issued Speaking question and attempt.';
