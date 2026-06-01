-- BandForge Phase 2 — new tables (Section 2.2)
-- Do NOT run against users / mock_tests (Phase 1 — already exist).
-- Apply in Supabase SQL Editor or: supabase db push

-- ---------------------------------------------------------------------------
-- QUESTIONS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS questions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  mock_test_id uuid NOT NULL REFERENCES mock_tests(id) ON DELETE CASCADE,
  module varchar(20) NOT NULL,
  part smallint,
  question_type varchar(40) NOT NULL,
  question_number integer NOT NULL,
  prompt text NOT NULL,
  passage_text text,
  audio_url text,
  options jsonb,
  correct_answer text,
  skill_tag varchar(40),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT questions_module_check CHECK (
    module IN ('reading', 'listening', 'writing', 'speaking')
  )
);

CREATE INDEX IF NOT EXISTS idx_questions_mock_test_id ON questions (mock_test_id);
CREATE INDEX IF NOT EXISTS idx_questions_mock_test_module ON questions (mock_test_id, module);

COMMENT ON TABLE questions IS 'Per-question content for a mock test module';
COMMENT ON COLUMN questions.options IS 'MCQ options: [{"label":"A","text":"..."}, ...]';

-- ---------------------------------------------------------------------------
-- TEST_ATTEMPTS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS test_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  mock_test_id uuid REFERENCES mock_tests(id),
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  status varchar(20) NOT NULL DEFAULT 'in_progress',
  CONSTRAINT test_attempts_status_check CHECK (
    status IN ('in_progress', 'completed', 'abandoned')
  )
);

CREATE INDEX IF NOT EXISTS idx_test_attempts_user_id ON test_attempts (user_id);
CREATE INDEX IF NOT EXISTS idx_test_attempts_mock_test_id ON test_attempts (mock_test_id);

-- ---------------------------------------------------------------------------
-- ANSWERS
-- NOTE: Build Manual Section 2.2 was truncated after `id` in the handoff.
-- Columns below match A2 (session) + A3 (auto-scorer) — confirm with founder.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS answers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_id uuid NOT NULL REFERENCES test_attempts(id) ON DELETE CASCADE,
  question_id uuid NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  user_answer text,
  is_correct boolean,
  answered_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT answers_attempt_question_unique UNIQUE (attempt_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_answers_attempt_id ON answers (attempt_id);
CREATE INDEX IF NOT EXISTS idx_answers_question_id ON answers (question_id);

-- ---------------------------------------------------------------------------
-- MODULE_SCORES
-- Per-module band after scoring (A3 + score report). Confirm with founder.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS module_scores (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_id uuid NOT NULL REFERENCES test_attempts(id) ON DELETE CASCADE,
  module varchar(20) NOT NULL,
  raw_score integer,
  band numeric(2, 1),
  scored_at timestamptz DEFAULT now(),
  CONSTRAINT module_scores_module_check CHECK (
    module IN ('reading', 'listening', 'writing', 'speaking')
  ),
  CONSTRAINT module_scores_attempt_module_unique UNIQUE (attempt_id, module)
);

CREATE INDEX IF NOT EXISTS idx_module_scores_attempt_id ON module_scores (attempt_id);

-- ---------------------------------------------------------------------------
-- SPEAKING_REVIEWS
-- Human reviewer queue (C4). Confirm column list with founder.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS speaking_reviews (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_id uuid NOT NULL REFERENCES test_attempts(id) ON DELETE CASCADE,
  status varchar(20) NOT NULL DEFAULT 'pending',
  human_band numeric(2, 1),
  reviewer_notes text,
  reviewed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT speaking_reviews_status_check CHECK (
    status IN ('pending', 'in_review', 'completed')
  )
);

CREATE INDEX IF NOT EXISTS idx_speaking_reviews_attempt_id ON speaking_reviews (attempt_id);
CREATE INDEX IF NOT EXISTS idx_speaking_reviews_status ON speaking_reviews (status);
