-- Payments foundation: plans catalog, payments, subscriptions, and webhook event log.
-- Razorpay is the processor only. Supabase owns subscription/access state.

-- plans: catalog of purchasable plans. Price is owned by the DB, in paise.
CREATE TABLE IF NOT EXISTS plans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text NOT NULL UNIQUE,
  name text NOT NULL,
  description text,
  amount integer NOT NULL,
  currency text NOT NULL DEFAULT 'INR',
  duration_days integer NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  sort_order smallint NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT plans_amount_positive CHECK (amount > 0),
  CONSTRAINT plans_duration_positive CHECK (duration_days > 0)
);

COMMENT ON TABLE plans IS 'Purchasable plan catalog; amount is server-owned, stored in paise.';

-- payments: one row per order attempt (created -> paid/failed/refunded).
CREATE TABLE IF NOT EXISTS payments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  plan_id uuid REFERENCES plans(id) ON DELETE SET NULL,
  razorpay_order_id text NOT NULL UNIQUE,
  razorpay_payment_id text UNIQUE,
  razorpay_signature text,
  amount integer NOT NULL,
  currency text NOT NULL DEFAULT 'INR',
  status varchar(20) NOT NULL DEFAULT 'created',
  notes jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT payments_status_check CHECK (
    status IN ('created', 'paid', 'failed', 'refunded')
  )
);

CREATE INDEX IF NOT EXISTS idx_payments_user ON payments (user_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments (status);
CREATE INDEX IF NOT EXISTS idx_payments_created_at ON payments (created_at DESC);

COMMENT ON TABLE payments IS 'Razorpay order/payment attempts. notes is Supabase-only metadata, never mirrored to Razorpay.';

-- subscriptions: DB-owned entitlement state.
CREATE TABLE IF NOT EXISTS subscriptions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  plan_id uuid NOT NULL REFERENCES plans(id) ON DELETE RESTRICT,
  payment_id uuid REFERENCES payments(id) ON DELETE SET NULL,
  starts_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  status varchar(20) NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT subscriptions_status_check CHECK (
    status IN ('active', 'expired', 'cancelled')
  )
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions (user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_active
  ON subscriptions (user_id, status, expires_at);

COMMENT ON TABLE subscriptions IS 'Source of truth for premium access. Active when status = active AND expires_at > now().';

-- payment_events: verified Razorpay webhook events for idempotency + audit.
CREATE TABLE IF NOT EXISTS payment_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  razorpay_event_id text UNIQUE,
  event_type text NOT NULL,
  payment_id uuid REFERENCES payments(id) ON DELETE SET NULL,
  razorpay_order_id text,
  razorpay_payment_id text,
  payload jsonb,
  processed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_payment_events_type ON payment_events (event_type);
CREATE INDEX IF NOT EXISTS idx_payment_events_order ON payment_events (razorpay_order_id);

COMMENT ON TABLE payment_events IS 'Verified Razorpay webhook events; unique razorpay_event_id guarantees idempotent processing.';

-- Seed initial plans (idempotent).
INSERT INTO plans (slug, name, description, amount, currency, duration_days, sort_order) VALUES
  ('starter_monthly', 'Starter', 'Selected mock tests with instant Listening & Reading scoring.', 49900, 'INR', 30, 1),
  ('premium_monthly', 'Premium', 'Full mock access with examiner-reviewed Writing & Speaking.', 99900, 'INR', 30, 2),
  ('premium_yearly', 'Premium Annual', 'Everything in Premium for a full year at the best value.', 999900, 'INR', 365, 3)
ON CONFLICT (slug) DO NOTHING;
