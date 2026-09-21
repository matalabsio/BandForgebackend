-- Internship applicant screening (same 4 skills as diagnostic; Groq scores W/S).

CREATE TABLE IF NOT EXISTS intern_applications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  access_token text NOT NULL UNIQUE,
  full_name text NOT NULL,
  email text NOT NULL,
  phone text NOT NULL DEFAULT '',
  college text NOT NULL DEFAULT '',
  role_applied text NOT NULL DEFAULT 'fullstack',
  status text NOT NULL DEFAULT 'in_progress',
  current_module text NOT NULL DEFAULT 'listening',
  listening_band numeric(3,1),
  reading_band numeric(3,1),
  writing_band numeric(3,1),
  speaking_band numeric(3,1),
  aggregate_band numeric(3,1),
  answers jsonb NOT NULL DEFAULT '{}'::jsonb,
  review jsonb,
  writing_evaluation jsonb,
  speaking_evaluation jsonb,
  writing_eval_pending boolean NOT NULL DEFAULT false,
  writing_eval_essay_hash text,
  writing_eval_error text,
  pack_version text,
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT intern_applications_status_check CHECK (
    status IN ('in_progress', 'processing', 'completed')
  ),
  CONSTRAINT intern_applications_module_check CHECK (
    current_module IN ('listening', 'reading', 'writing', 'speaking')
  ),
  CONSTRAINT intern_applications_role_check CHECK (
    role_applied IN ('frontend', 'backend', 'fullstack', 'product', 'other')
  )
);

CREATE INDEX IF NOT EXISTS idx_intern_applications_email
  ON intern_applications (lower(email));

CREATE INDEX IF NOT EXISTS idx_intern_applications_created
  ON intern_applications (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_intern_applications_status
  ON intern_applications (status, created_at DESC);

COMMENT ON TABLE intern_applications IS
  'Internship applicant screening: L/R client-scored, W/S via Groq (free tier).';

ALTER TABLE intern_applications ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE intern_applications FROM anon, authenticated;
GRANT ALL ON TABLE intern_applications TO service_role;
