-- Persist completed diagnostic results for logged-in users (admin + dashboard).

CREATE TABLE IF NOT EXISTS diagnostic_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  client_attempt_id text NOT NULL,
  status text NOT NULL DEFAULT 'completed',
  listening_band numeric(2, 1),
  reading_band numeric(2, 1),
  writing_band numeric(2, 1),
  speaking_band numeric(2, 1),
  aggregate_band numeric(2, 1),
  review jsonb,
  pack_version text,
  started_at timestamptz,
  completed_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT diagnostic_attempts_status_check CHECK (
    status IN ('in_progress', 'completed')
  ),
  CONSTRAINT diagnostic_attempts_user_client_unique UNIQUE (user_id, client_attempt_id)
);

CREATE INDEX IF NOT EXISTS idx_diagnostic_attempts_user_id
  ON diagnostic_attempts (user_id);

CREATE INDEX IF NOT EXISTS idx_diagnostic_attempts_completed_at
  ON diagnostic_attempts (completed_at DESC);

COMMENT ON TABLE diagnostic_attempts IS 'Client-scored diagnostic funnel results synced from /diagnostic/*';
