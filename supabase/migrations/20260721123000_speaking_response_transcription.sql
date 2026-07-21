-- Durable per-response Whisper jobs, leases, retries, and fluency snapshots.
ALTER TABLE speaking_responses
  ADD COLUMN IF NOT EXISTS transcription_status varchar(20) NOT NULL DEFAULT 'not_queued',
  ADD COLUMN IF NOT EXISTS transcription_attempts integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS transcription_error text,
  ADD COLUMN IF NOT EXISTS transcription_provider varchar(80),
  ADD COLUMN IF NOT EXISTS transcription_model varchar(120),
  ADD COLUMN IF NOT EXISTS transcription_lease_token uuid,
  ADD COLUMN IF NOT EXISTS transcription_lease_expires_at timestamptz,
  ADD COLUMN IF NOT EXISTS transcription_next_attempt_at timestamptz,
  ADD COLUMN IF NOT EXISTS transcribed_at timestamptz,
  ADD COLUMN IF NOT EXISTS transcript_words jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS fluency_metrics jsonb,
  ADD COLUMN IF NOT EXISTS metrics_version varchar(40),
  ADD COLUMN IF NOT EXISTS metrics_source_checksum varchar(64);

ALTER TABLE speaking_responses
  DROP CONSTRAINT IF EXISTS speaking_responses_transcription_status_check;

ALTER TABLE speaking_responses
  ADD CONSTRAINT speaking_responses_transcription_status_check CHECK (
    transcription_status IN (
      'not_queued', 'queued', 'processing', 'retry_wait', 'completed', 'failed'
    )
  );

CREATE INDEX IF NOT EXISTS idx_speaking_response_transcription_queue
  ON speaking_responses (transcription_status, transcription_next_attempt_at, sequence_number)
  WHERE transcription_status IN ('queued', 'processing', 'retry_wait');

CREATE OR REPLACE FUNCTION claim_speaking_response_transcription(
  p_response_id uuid,
  p_lease_token uuid,
  p_lease_seconds integer DEFAULT 300
)
RETURNS SETOF speaking_responses
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN QUERY
  UPDATE speaking_responses AS sr
  SET transcription_status = 'processing',
      transcription_attempts = sr.transcription_attempts + 1,
      transcription_lease_token = p_lease_token,
      transcription_lease_expires_at =
        now() + make_interval(secs => greatest(30, p_lease_seconds)),
      transcription_error = NULL,
      updated_at = now()
  WHERE sr.id = p_response_id
    AND sr.status = 'confirmed'
    AND (
      sr.transcription_status = 'queued'
      OR (
        sr.transcription_status = 'retry_wait'
        AND coalesce(sr.transcription_next_attempt_at, now()) <= now()
      )
      OR (
        sr.transcription_status = 'processing'
        AND sr.transcription_lease_expires_at < now()
      )
    )
  RETURNING sr.*;
END;
$$;

REVOKE ALL ON FUNCTION claim_speaking_response_transcription(uuid, uuid, integer)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION claim_speaking_response_transcription(uuid, uuid, integer)
  TO service_role;

COMMENT ON FUNCTION claim_speaking_response_transcription IS
  'Atomically claims one confirmed response; expired leases may be reclaimed.';
