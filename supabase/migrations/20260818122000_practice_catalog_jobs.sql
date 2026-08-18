-- Durable practice catalog jobs (publish fan-out).
-- Notification outbox is email/WhatsApp-only; this table is the practice job
-- lease/retry outbox, following the same claim + SKIP LOCKED pattern.

CREATE TABLE IF NOT EXISTS practice_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_type text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  idempotency_key text NOT NULL UNIQUE,
  status text NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'processing', 'retry', 'done', 'failed')),
  attempts integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 8,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  lease_token uuid,
  lease_expires_at timestamptz,
  last_error text,
  result jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_practice_jobs_claim
  ON practice_jobs (status, next_attempt_at, created_at);

COMMENT ON TABLE practice_jobs IS
  'Leased outbox for practice.catalog_changed publish fan-out. Not notification_outbox.';

ALTER TABLE practice_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE practice_jobs FROM PUBLIC;
REVOKE ALL ON TABLE practice_jobs FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE practice_jobs TO service_role;

CREATE INDEX IF NOT EXISTS idx_user_learning_profiles_active_plan
  ON user_learning_profiles (user_id)
  WHERE plan_tier = 'full_skill_program';

CREATE OR REPLACE FUNCTION enqueue_practice_catalog_changed(
  p_practice_set_id uuid,
  p_hub_id uuid,
  p_skill text,
  p_reason text DEFAULT 'published'
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_id uuid;
  v_key text;
  v_reason text := COALESCE(NULLIF(BTRIM(p_reason), ''), 'published');
BEGIN
  IF p_practice_set_id IS NULL OR p_hub_id IS NULL OR COALESCE(BTRIM(p_skill), '') = '' THEN
    RETURN NULL;
  END IF;
  v_key := 'practice.catalog_changed:' || v_reason || ':' || p_practice_set_id::text;

  INSERT INTO practice_jobs (
    job_type, payload, idempotency_key, status, next_attempt_at
  )
  VALUES (
    'practice.catalog_changed',
    jsonb_build_object(
      'practice_set_id', p_practice_set_id,
      'hub_id', p_hub_id,
      'skill', p_skill,
      'reason', v_reason
    ),
    v_key,
    'queued',
    now()
  )
  ON CONFLICT (idempotency_key) DO UPDATE
    SET payload = EXCLUDED.payload,
        updated_at = now(),
        status = CASE
          WHEN practice_jobs.status IN ('done', 'failed') THEN 'queued'
          ELSE practice_jobs.status
        END,
        next_attempt_at = CASE
          WHEN practice_jobs.status IN ('done', 'failed') THEN now()
          ELSE practice_jobs.next_attempt_at
        END,
        last_error = CASE
          WHEN practice_jobs.status IN ('done', 'failed') THEN NULL
          ELSE practice_jobs.last_error
        END,
        result = CASE
          WHEN practice_jobs.status IN ('done', 'failed') THEN NULL
          ELSE practice_jobs.result
        END,
        attempts = CASE
          WHEN practice_jobs.status IN ('done', 'failed') THEN 0
          ELSE practice_jobs.attempts
        END,
        lease_token = CASE
          WHEN practice_jobs.status IN ('done', 'failed') THEN NULL
          ELSE practice_jobs.lease_token
        END
  RETURNING id INTO v_id;
  RETURN v_id;
END;
$$;

REVOKE ALL ON FUNCTION enqueue_practice_catalog_changed(uuid, uuid, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION enqueue_practice_catalog_changed(uuid, uuid, text, text) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION enqueue_practice_catalog_changed(uuid, uuid, text, text) TO service_role;

CREATE OR REPLACE FUNCTION claim_practice_jobs(
  p_batch_size integer DEFAULT 5,
  p_lease_seconds integer DEFAULT 300
)
RETURNS SETOF practice_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN QUERY
  WITH candidates AS (
    SELECT id
    FROM practice_jobs
    WHERE (
      status IN ('queued', 'retry') AND next_attempt_at <= now()
    ) OR (
      status = 'processing' AND lease_expires_at < now()
    )
    ORDER BY next_attempt_at, created_at
    FOR UPDATE SKIP LOCKED
    LIMIT LEAST(GREATEST(p_batch_size, 1), 20)
  )
  UPDATE practice_jobs o
  SET status = 'processing',
      attempts = o.attempts + 1,
      lease_token = gen_random_uuid(),
      lease_expires_at = now() + make_interval(secs => LEAST(GREATEST(p_lease_seconds, 30), 1800)),
      updated_at = now()
  FROM candidates c
  WHERE o.id = c.id
  RETURNING o.*;
END;
$$;

REVOKE ALL ON FUNCTION claim_practice_jobs(integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION claim_practice_jobs(integer, integer) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION claim_practice_jobs(integer, integer) TO service_role;

CREATE OR REPLACE FUNCTION list_active_personalized_plan_users(
  p_after_user_id uuid DEFAULT NULL,
  p_limit integer DEFAULT 50
)
RETURNS TABLE(user_id uuid)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN QUERY
  SELECT ulp.user_id
  FROM user_learning_profiles ulp
  WHERE ulp.plan_tier = 'full_skill_program'
    AND ulp.study_plan IS NOT NULL
    AND jsonb_typeof(ulp.study_plan) = 'object'
    AND ulp.study_plan <> '{}'::jsonb
    AND COALESCE(ulp.exam_date, NULLIF(ulp.study_plan->>'exam_date', '')::date) >= CURRENT_DATE
    AND EXISTS (
      SELECT 1
      FROM subscriptions s
      JOIN plans p ON p.id = s.plan_id
      WHERE s.user_id = ulp.user_id
        AND s.status = 'active'
        AND s.expires_at > now()
        AND p.slug = 'full_skill_program'
    )
    AND (p_after_user_id IS NULL OR ulp.user_id > p_after_user_id)
  ORDER BY ulp.user_id
  LIMIT LEAST(GREATEST(COALESCE(p_limit, 50), 1), 200);
END;
$$;

REVOKE ALL ON FUNCTION list_active_personalized_plan_users(uuid, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION list_active_personalized_plan_users(uuid, integer) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION list_active_personalized_plan_users(uuid, integer) TO service_role;

-- Same-transaction publish + outbox insert so a crash after status=published
-- cannot permanently lose practice.catalog_changed.
CREATE OR REPLACE FUNCTION apply_practice_set_status(
  p_set_id uuid,
  p_status text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_prev text;
  v_hub uuid;
  v_skill text;
  v_job uuid;
BEGIN
  IF p_set_id IS NULL OR COALESCE(BTRIM(p_status), '') = '' THEN
    RAISE EXCEPTION 'apply_practice_set_status: invalid args';
  END IF;

  SELECT ps.status INTO v_prev
  FROM practice_sets ps
  WHERE ps.id = p_set_id
  FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'practice set not found';
  END IF;

  UPDATE practice_sets
  SET status = p_status
  WHERE id = p_set_id;

  v_job := NULL;
  IF p_status = 'published' AND v_prev IS DISTINCT FROM 'published' THEN
    SELECT ph.id INTO v_hub
    FROM practice_hubs ph
    WHERE ph.set_id = p_set_id
    ORDER BY ph.sort_order, ph.created_at
    LIMIT 1;

    SELECT pb.skill INTO v_skill
    FROM practice_sets ps
    JOIN practice_banks pb ON pb.id = ps.bank_id
    WHERE ps.id = p_set_id;

    IF v_hub IS NOT NULL AND COALESCE(BTRIM(v_skill), '') <> '' THEN
      v_job := enqueue_practice_catalog_changed(
        p_set_id, v_hub, lower(BTRIM(v_skill)), 'published'
      );
    END IF;
  END IF;

  RETURN jsonb_build_object(
    'prev', v_prev,
    'status', p_status,
    'hub_id', v_hub,
    'job_id', v_job
  );
END;
$$;

REVOKE ALL ON FUNCTION apply_practice_set_status(uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION apply_practice_set_status(uuid, text) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION apply_practice_set_status(uuid, text) TO service_role;
