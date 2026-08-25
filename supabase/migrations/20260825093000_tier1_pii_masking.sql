-- Tier 1 PII masking for non-prod DB refreshes.
-- Default: DISABLED. Enable only on staging/local after restore — never on production
-- without an explicit ops decision.
--
-- When enabled:
--   1) mask_tier1_pii_backfill() anonymizes existing rows
--   2) BEFORE INSERT/UPDATE triggers mask new writes of Tier 1 columns

CREATE TABLE IF NOT EXISTS public.pii_masking_config (
  id integer PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  enabled boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO public.pii_masking_config (id, enabled)
VALUES (1, false)
ON CONFLICT (id) DO NOTHING;

ALTER TABLE public.pii_masking_config ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.pii_masking_is_enabled()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT COALESCE(
    (SELECT enabled FROM public.pii_masking_config WHERE id = 1),
    false
  );
$$;

CREATE OR REPLACE FUNCTION public.pii_mask_email(p_id uuid)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT 'user_' || left(md5(p_id::text), 12) || '@masked.local';
$$;

CREATE OR REPLACE FUNCTION public.pii_mask_phone(p_id uuid)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT '+9100' || lpad(
    (
      (
        (('x' || substr(md5(p_id::text), 1, 8))::bit(32)::int) & 2147483647
      ) % 100000000
    )::text,
    8,
    '0'
  );
$$;

CREATE OR REPLACE FUNCTION public.pii_mask_name(p_id uuid)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT 'Masked User ' || left(replace(p_id::text, '-', ''), 8);
$$;

CREATE OR REPLACE FUNCTION public.pii_mask_token(p_id uuid)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT encode(digest('masked:' || p_id::text, 'sha256'), 'hex');
$$;

-- ---------------------------------------------------------------------------
-- Backfill (idempotent)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.mask_tier1_pii_backfill()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  n_users int := 0;
  n_leads int := 0;
  n_diag int := 0;
  n_otp int := 0;
  n_email_otp int := 0;
  n_outbox int := 0;
  n_reset int := 0;
  n_sessions int := 0;
BEGIN
  UPDATE public.users
  SET
    email = CASE WHEN email IS NOT NULL THEN public.pii_mask_email(id) ELSE email END,
    phone = CASE WHEN phone IS NOT NULL THEN public.pii_mask_phone(id) ELSE phone END,
    full_name = CASE WHEN full_name IS NOT NULL THEN public.pii_mask_name(id) ELSE full_name END,
    password_hash = CASE
      WHEN password_hash IS NOT NULL THEN public.pii_mask_token(id)
      ELSE password_hash
    END,
    updated_at = now()
  WHERE
    (email IS NOT NULL AND email !~ '@masked\.local$')
    OR (phone IS NOT NULL AND phone !~ '^\+9100')
    OR (full_name IS NOT NULL AND full_name !~ '^Masked User ')
    OR (password_hash IS NOT NULL AND password_hash <> public.pii_mask_token(id));
  GET DIAGNOSTICS n_users = ROW_COUNT;

  UPDATE public.signup_leads
  SET
    email = CASE WHEN email IS NOT NULL THEN public.pii_mask_email(id) ELSE email END,
    phone = CASE WHEN phone IS NOT NULL THEN public.pii_mask_phone(id) ELSE phone END,
    full_name = CASE WHEN full_name IS NOT NULL THEN public.pii_mask_name(id) ELSE full_name END,
    updated_at = now()
  WHERE
    (email IS NOT NULL AND email !~ '@masked\.local$')
    OR (phone IS NOT NULL AND phone !~ '^\+9100')
    OR (full_name IS NOT NULL AND full_name !~ '^Masked User ');
  GET DIAGNOSTICS n_leads = ROW_COUNT;

  UPDATE public.diagnostic_review_submissions
  SET
    email = CASE WHEN email IS NOT NULL THEN public.pii_mask_email(id) ELSE email END,
    phone = public.pii_mask_phone(id),
    full_name = public.pii_mask_name(id)
  WHERE
    (email IS NOT NULL AND email !~ '@masked\.local$')
    OR phone !~ '^\+9100'
    OR full_name !~ '^Masked User ';
  GET DIAGNOSTICS n_diag = ROW_COUNT;

  UPDATE public.otp_verifications
  SET
    phone = public.pii_mask_phone(id),
    code_hash = public.pii_mask_token(id)
  WHERE phone !~ '^\+9100' OR code_hash <> public.pii_mask_token(id);
  GET DIAGNOSTICS n_otp = ROW_COUNT;

  UPDATE public.email_otp_verifications
  SET
    email = public.pii_mask_email(id),
    code_hash = public.pii_mask_token(id)
  WHERE email !~ '@masked\.local$' OR code_hash <> public.pii_mask_token(id);
  GET DIAGNOSTICS n_email_otp = ROW_COUNT;

  UPDATE public.notification_outbox
  SET recipient_snapshot = CASE
    WHEN channel = 'email' THEN public.pii_mask_email(id)
    ELSE public.pii_mask_phone(id)
  END
  WHERE recipient_snapshot !~ '@masked\.local$'
    AND recipient_snapshot !~ '^\+9100';
  GET DIAGNOSTICS n_outbox = ROW_COUNT;

  UPDATE public.password_reset_tokens
  SET token_hash = public.pii_mask_token(id)
  WHERE token_hash <> public.pii_mask_token(id);
  GET DIAGNOSTICS n_reset = ROW_COUNT;

  UPDATE public.refresh_sessions
  SET
    token_hash = public.pii_mask_token(id),
    ip_address = '0.0.0.0',
    user_agent = 'masked'
  WHERE token_hash <> public.pii_mask_token(id)
    OR COALESCE(ip_address, '') <> '0.0.0.0'
    OR COALESCE(user_agent, '') <> 'masked';
  GET DIAGNOSTICS n_sessions = ROW_COUNT;

  RETURN jsonb_build_object(
    'users', n_users,
    'signup_leads', n_leads,
    'diagnostic_review_submissions', n_diag,
    'otp_verifications', n_otp,
    'email_otp_verifications', n_email_otp,
    'notification_outbox', n_outbox,
    'password_reset_tokens', n_reset,
    'refresh_sessions', n_sessions
  );
END;
$$;

-- ---------------------------------------------------------------------------
-- Triggers (active only while pii_masking_config.enabled)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.trg_mask_tier1_users()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF NOT public.pii_masking_is_enabled() THEN
    RETURN NEW;
  END IF;
  IF NEW.email IS NOT NULL THEN
    NEW.email := public.pii_mask_email(NEW.id);
  END IF;
  IF NEW.phone IS NOT NULL THEN
    NEW.phone := public.pii_mask_phone(NEW.id);
  END IF;
  IF NEW.full_name IS NOT NULL THEN
    NEW.full_name := public.pii_mask_name(NEW.id);
  END IF;
  IF NEW.password_hash IS NOT NULL THEN
    NEW.password_hash := public.pii_mask_token(NEW.id);
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.trg_mask_tier1_signup_leads()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF NOT public.pii_masking_is_enabled() THEN
    RETURN NEW;
  END IF;
  IF NEW.email IS NOT NULL THEN
    NEW.email := public.pii_mask_email(NEW.id);
  END IF;
  IF NEW.phone IS NOT NULL THEN
    NEW.phone := public.pii_mask_phone(NEW.id);
  END IF;
  IF NEW.full_name IS NOT NULL THEN
    NEW.full_name := public.pii_mask_name(NEW.id);
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.trg_mask_tier1_diagnostic_review_submissions()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF NOT public.pii_masking_is_enabled() THEN
    RETURN NEW;
  END IF;
  IF NEW.email IS NOT NULL THEN
    NEW.email := public.pii_mask_email(NEW.id);
  END IF;
  NEW.phone := public.pii_mask_phone(NEW.id);
  NEW.full_name := public.pii_mask_name(NEW.id);
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.trg_mask_tier1_otp_verifications()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF NOT public.pii_masking_is_enabled() THEN
    RETURN NEW;
  END IF;
  NEW.phone := public.pii_mask_phone(NEW.id);
  NEW.code_hash := public.pii_mask_token(NEW.id);
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.trg_mask_tier1_email_otp_verifications()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF NOT public.pii_masking_is_enabled() THEN
    RETURN NEW;
  END IF;
  NEW.email := public.pii_mask_email(NEW.id);
  NEW.code_hash := public.pii_mask_token(NEW.id);
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.trg_mask_tier1_notification_outbox()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF NOT public.pii_masking_is_enabled() THEN
    RETURN NEW;
  END IF;
  IF NEW.channel = 'email' THEN
    NEW.recipient_snapshot := public.pii_mask_email(NEW.id);
  ELSE
    NEW.recipient_snapshot := public.pii_mask_phone(NEW.id);
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.trg_mask_tier1_password_reset_tokens()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF NOT public.pii_masking_is_enabled() THEN
    RETURN NEW;
  END IF;
  NEW.token_hash := public.pii_mask_token(NEW.id);
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.trg_mask_tier1_refresh_sessions()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF NOT public.pii_masking_is_enabled() THEN
    RETURN NEW;
  END IF;
  NEW.token_hash := public.pii_mask_token(NEW.id);
  NEW.ip_address := '0.0.0.0';
  NEW.user_agent := 'masked';
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_mask_tier1_users ON public.users;
CREATE TRIGGER trg_mask_tier1_users
  BEFORE INSERT OR UPDATE OF email, phone, full_name, password_hash
  ON public.users
  FOR EACH ROW
  EXECUTE FUNCTION public.trg_mask_tier1_users();

DROP TRIGGER IF EXISTS trg_mask_tier1_signup_leads ON public.signup_leads;
CREATE TRIGGER trg_mask_tier1_signup_leads
  BEFORE INSERT OR UPDATE OF email, phone, full_name
  ON public.signup_leads
  FOR EACH ROW
  EXECUTE FUNCTION public.trg_mask_tier1_signup_leads();

DROP TRIGGER IF EXISTS trg_mask_tier1_diagnostic_review_submissions
  ON public.diagnostic_review_submissions;
CREATE TRIGGER trg_mask_tier1_diagnostic_review_submissions
  BEFORE INSERT OR UPDATE OF email, phone, full_name
  ON public.diagnostic_review_submissions
  FOR EACH ROW
  EXECUTE FUNCTION public.trg_mask_tier1_diagnostic_review_submissions();

DROP TRIGGER IF EXISTS trg_mask_tier1_otp_verifications ON public.otp_verifications;
CREATE TRIGGER trg_mask_tier1_otp_verifications
  BEFORE INSERT OR UPDATE OF phone, code_hash
  ON public.otp_verifications
  FOR EACH ROW
  EXECUTE FUNCTION public.trg_mask_tier1_otp_verifications();

DROP TRIGGER IF EXISTS trg_mask_tier1_email_otp_verifications
  ON public.email_otp_verifications;
CREATE TRIGGER trg_mask_tier1_email_otp_verifications
  BEFORE INSERT OR UPDATE OF email, code_hash
  ON public.email_otp_verifications
  FOR EACH ROW
  EXECUTE FUNCTION public.trg_mask_tier1_email_otp_verifications();

DROP TRIGGER IF EXISTS trg_mask_tier1_notification_outbox ON public.notification_outbox;
CREATE TRIGGER trg_mask_tier1_notification_outbox
  BEFORE INSERT OR UPDATE OF recipient_snapshot, channel
  ON public.notification_outbox
  FOR EACH ROW
  EXECUTE FUNCTION public.trg_mask_tier1_notification_outbox();

DROP TRIGGER IF EXISTS trg_mask_tier1_password_reset_tokens
  ON public.password_reset_tokens;
CREATE TRIGGER trg_mask_tier1_password_reset_tokens
  BEFORE INSERT OR UPDATE OF token_hash
  ON public.password_reset_tokens
  FOR EACH ROW
  EXECUTE FUNCTION public.trg_mask_tier1_password_reset_tokens();

DROP TRIGGER IF EXISTS trg_mask_tier1_refresh_sessions ON public.refresh_sessions;
CREATE TRIGGER trg_mask_tier1_refresh_sessions
  BEFORE INSERT OR UPDATE OF token_hash, ip_address, user_agent
  ON public.refresh_sessions
  FOR EACH ROW
  EXECUTE FUNCTION public.trg_mask_tier1_refresh_sessions();

-- Lock RPCs to service_role (scripts / FastAPI). Anon must not enable or backfill.
REVOKE ALL ON FUNCTION public.pii_masking_is_enabled() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.mask_tier1_pii_backfill() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.pii_mask_email(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.pii_mask_phone(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.pii_mask_name(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.pii_mask_token(uuid) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.pii_masking_is_enabled() TO service_role;
GRANT EXECUTE ON FUNCTION public.mask_tier1_pii_backfill() TO service_role;
GRANT EXECUTE ON FUNCTION public.pii_mask_email(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.pii_mask_phone(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.pii_mask_name(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.pii_mask_token(uuid) TO service_role;

-- Trigger functions must be callable by roles that write rows.
GRANT EXECUTE ON FUNCTION public.trg_mask_tier1_users() TO postgres, service_role, authenticated, anon;
GRANT EXECUTE ON FUNCTION public.trg_mask_tier1_signup_leads() TO postgres, service_role, authenticated, anon;
GRANT EXECUTE ON FUNCTION public.trg_mask_tier1_diagnostic_review_submissions() TO postgres, service_role, authenticated, anon;
GRANT EXECUTE ON FUNCTION public.trg_mask_tier1_otp_verifications() TO postgres, service_role, authenticated, anon;
GRANT EXECUTE ON FUNCTION public.trg_mask_tier1_email_otp_verifications() TO postgres, service_role, authenticated, anon;
GRANT EXECUTE ON FUNCTION public.trg_mask_tier1_notification_outbox() TO postgres, service_role, authenticated, anon;
GRANT EXECUTE ON FUNCTION public.trg_mask_tier1_password_reset_tokens() TO postgres, service_role, authenticated, anon;
GRANT EXECUTE ON FUNCTION public.trg_mask_tier1_refresh_sessions() TO postgres, service_role, authenticated, anon;

COMMENT ON TABLE public.pii_masking_config IS
  'Non-prod Tier 1 PII masking switch. Keep enabled=false on production.';
COMMENT ON FUNCTION public.mask_tier1_pii_backfill() IS
  'Idempotent Tier 1 anonymization for staging/local after DB refresh.';
