-- Row Level Security for payments tables.
-- Backend uses service_role (bypasses RLS). No client policies — blocks direct anon/authenticated access.

ALTER TABLE plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_events ENABLE ROW LEVEL SECURITY;

-- Public plan catalog readable by authenticated Supabase clients (future direct reads).
CREATE POLICY plans_select_authenticated ON plans
  FOR SELECT
  TO authenticated
  USING (is_active = true);

-- Users may read their own payment rows when using Supabase Auth JWT.
CREATE POLICY payments_select_own ON payments
  FOR SELECT
  TO authenticated
  USING (user_id = auth.uid());

CREATE POLICY subscriptions_select_own ON subscriptions
  FOR SELECT
  TO authenticated
  USING (user_id = auth.uid());

-- payment_events: no client policies — service_role only.
