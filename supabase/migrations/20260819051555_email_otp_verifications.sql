-- Email OTP verification records (parallel to phone otp_verifications; Phase 1 schema only)

CREATE TABLE IF NOT EXISTS email_otp_verifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL CHECK (email = lower(btrim(email)) AND length(email) > 0),
  code_hash text NOT NULL,
  purpose text NOT NULL DEFAULT 'login',
  attempts int NOT NULL DEFAULT 0,
  max_attempts int NOT NULL DEFAULT 5,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_email_otp_email_purpose ON email_otp_verifications (email, purpose);
CREATE INDEX IF NOT EXISTS idx_email_otp_expires ON email_otp_verifications (expires_at);
