-- Admin foundation: roles, mock status, question versions, audit logs, speaking extensions

-- ---------------------------------------------------------------------------
-- USERS — role + active flag
-- ---------------------------------------------------------------------------
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS role varchar(20) NOT NULL DEFAULT 'student';

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users
  ADD CONSTRAINT users_role_check
  CHECK (role IN ('student', 'admin', 'super_admin'));

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;

CREATE INDEX IF NOT EXISTS idx_users_role ON users (role);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users (is_active);

-- ---------------------------------------------------------------------------
-- MOCK_TESTS — lifecycle status (synced with is_published in app layer)
-- ---------------------------------------------------------------------------
ALTER TABLE mock_tests
  ADD COLUMN IF NOT EXISTS status varchar(20) NOT NULL DEFAULT 'draft';

ALTER TABLE mock_tests DROP CONSTRAINT IF EXISTS mock_tests_status_check;
ALTER TABLE mock_tests
  ADD CONSTRAINT mock_tests_status_check
  CHECK (status IN ('draft', 'published', 'archived'));

UPDATE mock_tests SET status = 'published' WHERE is_published = true AND status = 'draft';
UPDATE mock_tests SET status = 'draft' WHERE is_published = false AND status = 'draft';

CREATE INDEX IF NOT EXISTS idx_mock_tests_status ON mock_tests (status);

-- ---------------------------------------------------------------------------
-- QUESTIONS — explanation field for admin edits
-- ---------------------------------------------------------------------------
ALTER TABLE questions
  ADD COLUMN IF NOT EXISTS explanation text;

-- ---------------------------------------------------------------------------
-- QUESTION_VERSIONS — content history on admin edit
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS question_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  question_id uuid NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  version integer NOT NULL,
  content jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT question_versions_question_version_unique UNIQUE (question_id, version)
);

CREATE INDEX IF NOT EXISTS idx_question_versions_question_id
  ON question_versions (question_id);

COMMENT ON TABLE question_versions IS 'Snapshot of question content before each admin edit';

-- ---------------------------------------------------------------------------
-- ADMIN_AUDIT_LOGS — admin action trail
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin_audit_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  admin_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  action varchar(80) NOT NULL,
  resource_type varchar(40) NOT NULL,
  resource_id varchar(80),
  metadata jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_admin_id ON admin_audit_logs (admin_id);
CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_created_at ON admin_audit_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_resource
  ON admin_audit_logs (resource_type, resource_id);

-- ---------------------------------------------------------------------------
-- SPEAKING_REVIEWS — admin queue fields
-- ---------------------------------------------------------------------------
ALTER TABLE speaking_reviews
  ADD COLUMN IF NOT EXISTS ai_scores jsonb;

ALTER TABLE speaking_reviews
  ADD COLUMN IF NOT EXISTS transcript text;

ALTER TABLE speaking_reviews
  ADD COLUMN IF NOT EXISTS audio_url text;

ALTER TABLE speaking_reviews
  ADD COLUMN IF NOT EXISTS reviewer_id uuid REFERENCES users(id) ON DELETE SET NULL;
