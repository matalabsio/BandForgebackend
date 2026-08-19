-- Email OTP hardening: RLS lockdown, atomic create/cooldown, concurrency-safe attempts.

ALTER TABLE email_otp_verifications ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE email_otp_verifications FROM PUBLIC;
REVOKE ALL ON TABLE email_otp_verifications FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE email_otp_verifications TO service_role;

CREATE OR REPLACE FUNCTION create_email_otp_verification(
  p_email text,
  p_purpose text,
  p_code_hash text,
  p_max_attempts int,
  p_expires_at timestamptz,
  p_cooldown_seconds int
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_latest_created timestamptz;
  v_wait_seconds int;
  v_id uuid;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext(p_email || '|' || p_purpose));

  SELECT created_at
  INTO v_latest_created
  FROM email_otp_verifications
  WHERE email = p_email
    AND purpose = p_purpose
  ORDER BY created_at DESC
  LIMIT 1;

  IF v_latest_created IS NOT NULL
     AND v_latest_created > now() - make_interval(secs => p_cooldown_seconds) THEN
    v_wait_seconds := GREATEST(
      1,
      CEIL(
        EXTRACT(
          EPOCH FROM (
            v_latest_created + make_interval(secs => p_cooldown_seconds) - now()
          )
        )
      )::int
    );
    RETURN jsonb_build_object(
      'created', false,
      'cooldown', true,
      'wait_seconds', v_wait_seconds
    );
  END IF;

  INSERT INTO email_otp_verifications (
    email,
    code_hash,
    purpose,
    attempts,
    max_attempts,
    expires_at
  ) VALUES (
    p_email,
    p_code_hash,
    p_purpose,
    0,
    p_max_attempts,
    p_expires_at
  )
  RETURNING id INTO v_id;

  RETURN jsonb_build_object(
    'created', true,
    'verification_id', v_id
  );
END;
$$;

CREATE OR REPLACE FUNCTION increment_email_otp_attempt(p_verification_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_row email_otp_verifications%ROWTYPE;
BEGIN
  UPDATE email_otp_verifications
  SET attempts = attempts + 1
  WHERE id = p_verification_id
    AND consumed_at IS NULL
    AND attempts < max_attempts
  RETURNING * INTO v_row;

  IF FOUND THEN
    RETURN jsonb_build_object(
      'found', true,
      'incremented', true,
      'attempts', v_row.attempts,
      'max_attempts', v_row.max_attempts
    );
  END IF;

  SELECT * INTO v_row
  FROM email_otp_verifications
  WHERE id = p_verification_id;

  IF NOT FOUND THEN
    RETURN jsonb_build_object('found', false);
  END IF;

  RETURN jsonb_build_object(
    'found', true,
    'incremented', false,
    'attempts', v_row.attempts,
    'max_attempts', v_row.max_attempts,
    'consumed', v_row.consumed_at IS NOT NULL
  );
END;
$$;

REVOKE ALL ON FUNCTION public.create_email_otp_verification(
  text, text, text, int, timestamptz, int
) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.create_email_otp_verification(
  text, text, text, int, timestamptz, int
) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_email_otp_verification(
  text, text, text, int, timestamptz, int
) TO service_role;

REVOKE ALL ON FUNCTION public.increment_email_otp_attempt(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.increment_email_otp_attempt(uuid) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.increment_email_otp_attempt(uuid) TO service_role;
