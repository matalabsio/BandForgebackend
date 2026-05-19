-- Pre-auth signup leads (phone / email collected before MSG91 OTP is enabled)

CREATE TABLE IF NOT EXISTS signup_leads (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  phone text,
  email text,
  full_name text,
  channel text NOT NULL DEFAULT 'start_modal',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_signup_leads_phone
  ON signup_leads (phone) WHERE phone IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_signup_leads_email
  ON signup_leads (email) WHERE email IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_signup_leads_created
  ON signup_leads (created_at DESC);
