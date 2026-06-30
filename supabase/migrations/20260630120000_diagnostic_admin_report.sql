-- Admin diagnostic report: human Speaking scores + report email tracking.

ALTER TABLE diagnostic_review_submissions
  ADD COLUMN IF NOT EXISTS speaking_human_band numeric(2, 1);

ALTER TABLE diagnostic_review_submissions
  ADD COLUMN IF NOT EXISTS speaking_human_criteria_scores jsonb;

ALTER TABLE diagnostic_review_submissions
  ADD COLUMN IF NOT EXISTS speaking_reviewer_notes text;

ALTER TABLE diagnostic_review_submissions
  ADD COLUMN IF NOT EXISTS speaking_reviewer_id uuid REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE diagnostic_review_submissions
  ADD COLUMN IF NOT EXISTS speaking_reviewed_at timestamptz;

ALTER TABLE diagnostic_review_submissions
  ADD COLUMN IF NOT EXISTS report_email_sent_at timestamptz;

ALTER TABLE diagnostic_review_submissions
  ADD COLUMN IF NOT EXISTS report_email_sent_by uuid REFERENCES users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_diagnostic_review_submissions_report_sent
  ON diagnostic_review_submissions (report_email_sent_at DESC NULLS LAST);

COMMENT ON COLUMN diagnostic_review_submissions.speaking_human_band IS
  'Examiner-assigned Speaking band for marketing diagnostic funnel.';

COMMENT ON COLUMN diagnostic_review_submissions.report_email_sent_at IS
  'When the full diagnostic report card email was sent to the student.';
