-- Atomic payment mark-paid + subscription insert (idempotent on already-paid).

CREATE OR REPLACE FUNCTION confirm_payment_paid_bundle(
  p_razorpay_order_id text,
  p_razorpay_payment_id text,
  p_razorpay_signature text,
  p_starts_at timestamptz,
  p_expires_at timestamptz
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_payment payments%ROWTYPE;
  v_sub_id uuid;
BEGIN
  SELECT * INTO v_payment
  FROM payments
  WHERE razorpay_order_id = p_razorpay_order_id
  FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'payment_not_found';
  END IF;

  IF v_payment.status = 'paid' THEN
    RETURN jsonb_build_object(
      'already_paid', true,
      'payment_id', v_payment.id,
      'user_id', v_payment.user_id
    );
  END IF;

  IF v_payment.plan_id IS NULL THEN
    RAISE EXCEPTION 'plan_not_found';
  END IF;

  UPDATE payments
  SET status = 'paid',
      razorpay_payment_id = p_razorpay_payment_id,
      razorpay_signature = p_razorpay_signature,
      updated_at = now()
  WHERE id = v_payment.id;

  INSERT INTO subscriptions (
    user_id, plan_id, payment_id, starts_at, expires_at, status
  )
  VALUES (
    v_payment.user_id,
    v_payment.plan_id,
    v_payment.id,
    p_starts_at,
    p_expires_at,
    'active'
  )
  RETURNING id INTO v_sub_id;

  RETURN jsonb_build_object(
    'already_paid', false,
    'payment_id', v_payment.id,
    'subscription_id', v_sub_id,
    'user_id', v_payment.user_id
  );
END;
$$;

REVOKE ALL ON FUNCTION confirm_payment_paid_bundle(text, text, text, timestamptz, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION confirm_payment_paid_bundle(text, text, text, timestamptz, timestamptz) TO service_role;
