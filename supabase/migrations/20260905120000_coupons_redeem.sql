

CREATE TABLE IF NOT EXISTS coupons (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code text NOT NULL,
  discount_percent integer NOT NULL DEFAULT 100,
  max_redemptions integer NOT NULL DEFAULT 1,
  redemption_count integer NOT NULL DEFAULT 0,
  is_active boolean NOT NULL DEFAULT true,
  starts_at timestamptz,
  expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT coupons_code_upper CHECK (code = upper(code)),
  CONSTRAINT coupons_discount_v1 CHECK (discount_percent = 100),
  CONSTRAINT coupons_max_redemptions_positive CHECK (max_redemptions > 0),
  CONSTRAINT coupons_redemption_count_nonneg CHECK (redemption_count >= 0),
  CONSTRAINT coupons_redemption_count_cap CHECK (redemption_count <= max_redemptions)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_coupons_code_unique ON coupons (code);

COMMENT ON TABLE coupons IS '100% discount coupon catalog; redemption_count bumped atomically by redeem_coupon_bundle.';

CREATE TABLE IF NOT EXISTS coupon_redemptions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  coupon_id uuid NOT NULL REFERENCES coupons(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  payment_id uuid NOT NULL REFERENCES payments(id) ON DELETE RESTRICT,
  plan_id uuid NOT NULL REFERENCES plans(id) ON DELETE RESTRICT,
  redeemed_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT coupon_redemptions_coupon_unique UNIQUE (coupon_id),
  CONSTRAINT coupon_redemptions_user_unique UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_user ON coupon_redemptions (user_id);
CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_payment ON coupon_redemptions (payment_id);

COMMENT ON TABLE coupon_redemptions IS 'Audit of coupon grants; UNIQUE(coupon_id) = global one-use; UNIQUE(user_id) = one coupon per user.';

ALTER TABLE coupons ENABLE ROW LEVEL SECURITY;
ALTER TABLE coupon_redemptions ENABLE ROW LEVEL SECURITY;
-- No client policies — service_role only (matches payment_events).

CREATE OR REPLACE FUNCTION redeem_coupon_bundle(
  p_user_id uuid,
  p_plan_slug text,
  p_code text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_code text;
  v_coupon coupons%ROWTYPE;
  v_plan plans%ROWTYPE;
  v_payment_id uuid;
  v_sub_id uuid;
  v_redemption_id uuid;
  v_order_id text;
  v_pay_id text;
  v_starts_at timestamptz;
  v_expires_at timestamptz;
  v_existing_expiry timestamptz;
  v_now timestamptz := now();
BEGIN
  v_code := upper(trim(coalesce(p_code, '')));
  IF v_code = '' THEN
    RAISE EXCEPTION 'coupon_invalid';
  END IF;

  SELECT * INTO v_coupon
    FROM coupons
   WHERE code = v_code
   FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'coupon_invalid';
  END IF;

  IF NOT v_coupon.is_active THEN
    RAISE EXCEPTION 'coupon_inactive';
  END IF;

  IF v_coupon.starts_at IS NOT NULL AND v_coupon.starts_at > v_now THEN
    RAISE EXCEPTION 'coupon_expired';
  END IF;

  IF v_coupon.expires_at IS NOT NULL AND v_coupon.expires_at < v_now THEN
    RAISE EXCEPTION 'coupon_expired';
  END IF;

  IF v_coupon.redemption_count >= v_coupon.max_redemptions THEN
    RAISE EXCEPTION 'coupon_exhausted';
  END IF;

  IF EXISTS (
    SELECT 1 FROM coupon_redemptions WHERE user_id = p_user_id
  ) THEN
    RAISE EXCEPTION 'coupon_user_already_redeemed';
  END IF;

  SELECT * INTO v_plan
    FROM plans
   WHERE slug = p_plan_slug
     AND is_active = true;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'plan_not_found';
  END IF;

  -- Stack on any active subscription (same stacking idea as paid fulfillment).
  SELECT s.expires_at INTO v_existing_expiry
    FROM subscriptions s
   WHERE s.user_id = p_user_id
     AND s.status = 'active'
     AND s.expires_at > v_now
   ORDER BY s.expires_at DESC
   LIMIT 1;

  v_starts_at := coalesce(v_existing_expiry, v_now);
  IF v_starts_at < v_now THEN
    v_starts_at := v_now;
  END IF;
  v_expires_at := v_starts_at + make_interval(days => v_plan.duration_days);

  v_order_id := 'coupon_ord_' || replace(gen_random_uuid()::text, '-', '');
  v_pay_id := 'coupon_pay_' || replace(gen_random_uuid()::text, '-', '');

  INSERT INTO payments (
    user_id,
    plan_id,
    razorpay_order_id,
    razorpay_payment_id,
    razorpay_signature,
    amount,
    currency,
    status,
    notes
  )
  VALUES (
    p_user_id,
    v_plan.id,
    v_order_id,
    v_pay_id,
    NULL,
    0,
    v_plan.currency,
    'paid',
    jsonb_build_object(
      'source', 'coupon',
      'coupon_id', v_coupon.id::text,
      'coupon_code_last4', right(v_coupon.code, 4)
    )
  )
  RETURNING id INTO v_payment_id;

  INSERT INTO subscriptions (
    user_id, plan_id, payment_id, starts_at, expires_at, status
  )
  VALUES (
    p_user_id,
    v_plan.id,
    v_payment_id,
    v_starts_at,
    v_expires_at,
    'active'
  )
  RETURNING id INTO v_sub_id;

  INSERT INTO coupon_redemptions (
    coupon_id, user_id, payment_id, plan_id
  )
  VALUES (
    v_coupon.id, p_user_id, v_payment_id, v_plan.id
  )
  RETURNING id INTO v_redemption_id;

  UPDATE coupons
     SET redemption_count = redemption_count + 1
   WHERE id = v_coupon.id;

  RETURN jsonb_build_object(
    'ok', true,
    'coupon_id', v_coupon.id,
    'redemption_id', v_redemption_id,
    'payment_id', v_payment_id,
    'subscription_id', v_sub_id,
    'user_id', p_user_id,
    'plan_id', v_plan.id,
    'plan_slug', v_plan.slug,
    'razorpay_order_id', v_order_id,
    'razorpay_payment_id', v_pay_id,
    'starts_at', v_starts_at,
    'expires_at', v_expires_at
  );
EXCEPTION
  WHEN unique_violation THEN
    -- Concurrent redeem races on coupon_id or user_id uniqueness.
    IF EXISTS (
      SELECT 1 FROM coupon_redemptions WHERE user_id = p_user_id
    ) THEN
      RAISE EXCEPTION 'coupon_user_already_redeemed';
    END IF;
    RAISE EXCEPTION 'coupon_exhausted';
END;
$$;

REVOKE ALL ON FUNCTION public.redeem_coupon_bundle(uuid, text, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.redeem_coupon_bundle(uuid, text, text) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.redeem_coupon_bundle(uuid, text, text) TO service_role;

-- Coupon codes are NOT seeded here (avoid publishing redeemable secrets in git).
-- Apply locally / in ops: seed/coupons_seed.sql (gitignored).
