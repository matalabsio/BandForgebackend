-- English Forge Spoken English sessions (school coach — not IELTS speaking).

CREATE TABLE IF NOT EXISTS english_forge_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  grade_band varchar(8) NOT NULL,
  prompt_id text NOT NULL,
  prompt_title text NOT NULL,
  prompt_text text NOT NULL,
  listen_hint text,
  target_duration_sec integer NOT NULL DEFAULT 45,
  max_duration_sec integer NOT NULL DEFAULT 60,
  status varchar(32) NOT NULL DEFAULT 'active',
  guest_key text,
  user_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT english_forge_sessions_grade_check
    CHECK (grade_band IN ('1-3', '4-5', '6-8', '9-10')),
  CONSTRAINT english_forge_sessions_status_check
    CHECK (status IN ('active', 'finalized', 'failed'))
);

CREATE TABLE IF NOT EXISTS english_forge_responses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES english_forge_sessions(id) ON DELETE CASCADE,
  audio_key text NOT NULL,
  content_type varchar(100) NOT NULL,
  duration_sec integer NOT NULL,
  size_bytes integer NOT NULL,
  idempotency_key text NOT NULL,
  status varchar(32) NOT NULL DEFAULT 'pending_upload',
  upload_expires_at timestamptz,
  transcript text,
  transcription_status varchar(32) NOT NULL DEFAULT 'not_queued',
  transcription_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  confirmed_at timestamptz,
  CONSTRAINT english_forge_responses_status_check
    CHECK (status IN ('pending_upload', 'confirmed', 'failed')),
  CONSTRAINT english_forge_responses_transcription_check
    CHECK (
      transcription_status IN (
        'not_queued', 'queued', 'processing', 'completed', 'failed', 'stubbed'
      )
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ef_responses_session_idempotency
  ON english_forge_responses (session_id, idempotency_key);

CREATE INDEX IF NOT EXISTS idx_ef_responses_session
  ON english_forge_responses (session_id, created_at);

CREATE TABLE IF NOT EXISTS english_forge_evaluations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES english_forge_sessions(id) ON DELETE CASCADE,
  response_id uuid REFERENCES english_forge_responses(id) ON DELETE SET NULL,
  status varchar(32) NOT NULL DEFAULT 'pending',
  coach_card jsonb,
  error text,
  evaluator_version text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT english_forge_evaluations_status_check
    CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'stubbed'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ef_evaluations_one_per_session
  ON english_forge_evaluations (session_id);

ALTER TABLE english_forge_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE english_forge_responses ENABLE ROW LEVEL SECURITY;
ALTER TABLE english_forge_evaluations ENABLE ROW LEVEL SECURITY;

-- Service role only for writes; no authenticated client policies (guest API).

COMMENT ON TABLE english_forge_sessions IS
  'English Forge practice sessions (school Spoken English coach).';
COMMENT ON TABLE english_forge_responses IS
  'Per-session audio uploads for English Forge (R2 keys).';
COMMENT ON TABLE english_forge_evaluations IS
  'Coach-card evaluations for English Forge (no IELTS bands).';
