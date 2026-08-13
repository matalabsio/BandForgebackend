-- Diagnostic IELTS purpose/goal on the student profile (dashboard greeting).

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS ielts_purpose text,
  ADD COLUMN IF NOT EXISTS ielts_goal text;

ALTER TABLE users
  DROP CONSTRAINT IF EXISTS users_ielts_purpose_check;

ALTER TABLE users
  ADD CONSTRAINT users_ielts_purpose_check
  CHECK (
    ielts_purpose IS NULL
    OR ielts_purpose IN ('immigration', 'university', 'professional', 'general')
  );

ALTER TABLE users
  DROP CONSTRAINT IF EXISTS users_ielts_goal_check;

ALTER TABLE users
  ADD CONSTRAINT users_ielts_goal_check
  CHECK (
    ielts_goal IS NULL
    OR ielts_goal IN (
      'australian_pr',
      'canada_pr',
      'uk_visa',
      'study_abroad',
      'professional_registration',
      'other'
    )
  );

COMMENT ON COLUMN users.ielts_purpose IS
  'Diagnostic purpose: immigration | university | professional | general.';
COMMENT ON COLUMN users.ielts_goal IS
  'Diagnostic goal id used for dashboard greeting (Study Abroad / Migration Dream).';
