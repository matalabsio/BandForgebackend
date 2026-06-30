-- Richer webhook audit fields for payment_events.

ALTER TABLE payment_events
  ADD COLUMN IF NOT EXISTS headers jsonb,
  ADD COLUMN IF NOT EXISTS raw_payload jsonb,
  ADD COLUMN IF NOT EXISTS received_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS processing_status varchar(20) NOT NULL DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS processing_error text,
  ADD COLUMN IF NOT EXISTS retry_count smallint NOT NULL DEFAULT 0;

ALTER TABLE payment_events
  DROP CONSTRAINT IF EXISTS payment_events_processing_status_check;

ALTER TABLE payment_events
  ADD CONSTRAINT payment_events_processing_status_check CHECK (
    processing_status IN ('pending', 'processed', 'failed')
  );

-- Backfill raw_payload from legacy payload column.
UPDATE payment_events
SET raw_payload = payload
WHERE raw_payload IS NULL AND payload IS NOT NULL;

COMMENT ON COLUMN payment_events.headers IS
  'Sanitized webhook request headers (no signature values).';
COMMENT ON COLUMN payment_events.raw_payload IS
  'Verified webhook JSON body.';
COMMENT ON COLUMN payment_events.processing_status IS
  'pending | processed | failed';
