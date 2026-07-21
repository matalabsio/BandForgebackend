-- Direct-to-R2 Speaking upload sessions. Existing API-uploaded rows remain valid.

ALTER TABLE speaking_responses
  ADD COLUMN IF NOT EXISTS idempotency_key varchar(128),
  ADD COLUMN IF NOT EXISTS upload_expires_at timestamptz,
  ADD COLUMN IF NOT EXISTS confirmed_at timestamptz;

ALTER TABLE speaking_responses
  ALTER COLUMN content_sha256 DROP NOT NULL;

ALTER TABLE speaking_responses
  DROP CONSTRAINT IF EXISTS speaking_responses_status_check;

UPDATE speaking_responses
SET status = 'confirmed',
    confirmed_at = COALESCE(confirmed_at, updated_at, created_at)
WHERE status = 'uploaded';

ALTER TABLE speaking_responses
  ADD CONSTRAINT speaking_responses_status_check CHECK (
    status IN (
      'pending_upload',
      'confirmed',
      'processing',
      'processed',
      'failed'
    )
  );

ALTER TABLE speaking_responses
  DROP CONSTRAINT IF EXISTS speaking_responses_session_fields_check;

ALTER TABLE speaking_responses
  ADD CONSTRAINT speaking_responses_session_fields_check CHECK (
    status <> 'pending_upload'
    OR (
      idempotency_key IS NOT NULL
      AND upload_expires_at IS NOT NULL
      AND content_sha256 IS NULL
    )
  );

CREATE UNIQUE INDEX IF NOT EXISTS idx_speaking_responses_idempotency
  ON speaking_responses (attempt_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

COMMENT ON COLUMN speaking_responses.idempotency_key IS
  'Opaque key required to replay or confirm a direct R2 upload session.';
COMMENT ON COLUMN speaking_responses.upload_expires_at IS
  'Expiry of the server-issued presigned PUT session.';
COMMENT ON COLUMN speaking_responses.confirmed_at IS
  'Time the API verified R2 object metadata and accepted the response.';
