-- Standalone question bank linked to practice_sets (not mock_tests).

CREATE TABLE IF NOT EXISTS bank_sections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  practice_set_id uuid NOT NULL REFERENCES practice_sets(id) ON DELETE CASCADE,
  module text NOT NULL CHECK (module IN ('listening', 'reading', 'writing', 'speaking')),
  part smallint NOT NULL CHECK (part >= 1 AND part <= 4),
  title text,
  instructions text,
  audio_key text,
  passage_text text,
  image_url text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (practice_set_id, part)
);

CREATE INDEX IF NOT EXISTS idx_bank_sections_set ON bank_sections (practice_set_id);
CREATE INDEX IF NOT EXISTS idx_bank_sections_module ON bank_sections (module);

CREATE TABLE IF NOT EXISTS bank_questions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  section_id uuid NOT NULL REFERENCES bank_sections(id) ON DELETE CASCADE,
  question_number integer NOT NULL,
  question_type varchar(40) NOT NULL,
  prompt text NOT NULL,
  passage_text text,
  audio_url text,
  options jsonb,
  correct_answer text,
  explanation text,
  skill_tag varchar(40),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (section_id, question_number)
);

CREATE INDEX IF NOT EXISTS idx_bank_questions_section ON bank_questions (section_id);

CREATE TABLE IF NOT EXISTS practice_exercise_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  hub_id uuid NOT NULL REFERENCES practice_hubs(id) ON DELETE CASCADE,
  practice_set_id uuid NOT NULL REFERENCES practice_sets(id) ON DELETE CASCADE,
  section_id uuid REFERENCES bank_sections(id) ON DELETE SET NULL,
  part smallint NOT NULL DEFAULT 1,
  status text NOT NULL DEFAULT 'in_progress'
    CHECK (status IN ('in_progress', 'completed', 'abandoned')),
  answers jsonb NOT NULL DEFAULT '{}'::jsonb,
  score jsonb,
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_practice_exercise_attempts_user
  ON practice_exercise_attempts (user_id);
CREATE INDEX IF NOT EXISTS idx_practice_exercise_attempts_hub
  ON practice_exercise_attempts (hub_id);

ALTER TABLE bank_sections ENABLE ROW LEVEL SECURITY;
ALTER TABLE bank_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE practice_exercise_attempts ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE bank_sections IS
  'Reusable practice content unit per practice_set + part (standalone question bank).';
COMMENT ON TABLE bank_questions IS
  'Items in a bank section; not tied to mock_tests.';
COMMENT ON TABLE practice_exercise_attempts IS
  'Candidate attempts at hub bank exercises (personalized plan submit path).';
