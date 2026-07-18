-- One subscription row per payment (idempotent verify + webhook + fallback races).

CREATE UNIQUE INDEX IF NOT EXISTS idx_subscriptions_payment_id_unique
  ON subscriptions (payment_id)
  WHERE payment_id IS NOT NULL;

COMMENT ON INDEX idx_subscriptions_payment_id_unique IS
  'Guarantees at most one subscription per payment_id across dual-path fulfillment.';
