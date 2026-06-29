-- Writing human reviewer queue (mock tests) + diagnostic submission reviewer fields.

CREATE TABLE IF NOT EXISTS writing_reviews (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_id uuid NOT NULL REFERENCES test_attempts(id) ON DELETE CASCADE,
  status varchar(20) NOT NULL DEFAULT 'pending',
  human_band numeric(2, 1),
  human_criteria_scores jsonb,
  reviewer_notes text,
  reviewer_id uuid REFERENCES users(id) ON DELETE SET NULL,
  reviewed_at timestamptz,
  submission_meta jsonb,
  ai_scores jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT writing_reviews_status_check CHECK (
    status IN ('pending', 'in_review', 'completed')
  )
);

CREATE INDEX IF NOT EXISTS idx_writing_reviews_attempt_id ON writing_reviews (attempt_id);
CREATE INDEX IF NOT EXISTS idx_writing_reviews_status ON writing_reviews (status);

COMMENT ON TABLE writing_reviews IS
  'Human examiner queue for mock writing submissions.';

-- Diagnostic funnel: allow in_review + store human reviewer output.
ALTER TABLE diagnostic_review_submissions
  ADD COLUMN IF NOT EXISTS reviewer_id uuid REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE diagnostic_review_submissions
  ADD COLUMN IF NOT EXISTS reviewer_notes text;

ALTER TABLE diagnostic_review_submissions
  ADD COLUMN IF NOT EXISTS human_band numeric(2, 1);

ALTER TABLE diagnostic_review_submissions
  ADD COLUMN IF NOT EXISTS human_criteria_scores jsonb;

ALTER TABLE diagnostic_review_submissions
  ADD COLUMN IF NOT EXISTS reviewed_at timestamptz;

ALTER TABLE diagnostic_review_submissions
  DROP CONSTRAINT IF EXISTS diagnostic_review_submissions_status_check;

ALTER TABLE diagnostic_review_submissions
  ADD CONSTRAINT diagnostic_review_submissions_status_check CHECK (
    status IN ('pending_review', 'in_review', 'reviewed', 'cancelled')
  );
