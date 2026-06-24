-- Marketing diagnostic submissions queued for human examiner review.

CREATE TABLE IF NOT EXISTS diagnostic_review_submissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_attempt_id text NOT NULL UNIQUE,
  full_name text NOT NULL,
  phone text NOT NULL,
  email text,
  goal_label text,
  target_band numeric(2, 1),
  listening_band numeric(2, 1),
  reading_band numeric(2, 1),
  writing_band numeric(2, 1),
  speaking_band numeric(2, 1),
  aggregate_band numeric(2, 1),
  answers jsonb NOT NULL DEFAULT '{}'::jsonb,
  review jsonb,
  status text NOT NULL DEFAULT 'pending_review',
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT diagnostic_review_submissions_status_check CHECK (
    status IN ('pending_review', 'reviewed', 'cancelled')
  )
);

CREATE INDEX IF NOT EXISTS idx_diagnostic_review_submissions_status
  ON diagnostic_review_submissions (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_diagnostic_review_submissions_email
  ON diagnostic_review_submissions (lower(email))
  WHERE email IS NOT NULL;

COMMENT ON TABLE diagnostic_review_submissions IS
  'Free diagnostic funnel — lead + answers submitted for human band review (email delivery).';
