-- AI evaluations for diagnostic funnel (writing now; speaking later).

CREATE TABLE IF NOT EXISTS diagnostic_ai_evaluations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evaluation_type text NOT NULL,
  client_attempt_id text NOT NULL,
  essay_hash text NOT NULL,
  task_part integer NOT NULL DEFAULT 1,
  question_text text NOT NULL,
  essay_text text NOT NULL,
  word_count integer NOT NULL DEFAULT 0,
  sentence_count integer NOT NULL DEFAULT 0,
  paragraph_count integer NOT NULL DEFAULT 0,
  overall_band numeric(2, 1) NOT NULL,
  criteria_scores jsonb NOT NULL DEFAULT '{}'::jsonb,
  feedback jsonb NOT NULL DEFAULT '{}'::jsonb,
  raw_ai_response jsonb,
  prompt_version text NOT NULL DEFAULT 'v1',
  model_name text,
  evaluation_source text NOT NULL DEFAULT 'ai',
  evaluated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT diagnostic_ai_evaluations_type_check CHECK (
    evaluation_type IN ('writing', 'speaking')
  ),
  CONSTRAINT diagnostic_ai_evaluations_source_check CHECK (
    evaluation_source IN ('ai', 'fallback')
  ),
  CONSTRAINT diagnostic_ai_evaluations_hash_type_unique UNIQUE (essay_hash, evaluation_type),
  CONSTRAINT diagnostic_ai_evaluations_attempt_type_unique UNIQUE (client_attempt_id, evaluation_type)
);

CREATE INDEX IF NOT EXISTS idx_diagnostic_ai_evaluations_type_created
  ON diagnostic_ai_evaluations (evaluation_type, evaluated_at DESC);

COMMENT ON TABLE diagnostic_ai_evaluations IS
  'Groq/AI band evaluations for diagnostic funnel — one row per attempt per type.';

-- Link final submission to evaluation (no essay duplication).
ALTER TABLE diagnostic_review_submissions
  ADD COLUMN IF NOT EXISTS writing_evaluation_id uuid
  REFERENCES diagnostic_ai_evaluations (id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_diagnostic_review_submissions_writing_eval
  ON diagnostic_review_submissions (writing_evaluation_id)
  WHERE writing_evaluation_id IS NOT NULL;
