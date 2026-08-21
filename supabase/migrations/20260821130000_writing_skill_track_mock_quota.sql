-- Phase 5: atomic Writing Skill mock quota + exam_module set helpers.
-- Service-role RPCs only (backend uses service key).

CREATE OR REPLACE FUNCTION consume_user_program_mock_quota(p_usage_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  r user_program_usage;
BEGIN
  UPDATE user_program_usage
  SET
    mocks_used = mocks_used + 1,
    updated_at = now()
  WHERE id = p_usage_id
    AND mocks_used < mocks_granted
  RETURNING * INTO r;

  IF r.id IS NULL THEN
    RETURN NULL;
  END IF;

  RETURN to_jsonb(r);
END;
$$;

REVOKE ALL ON FUNCTION consume_user_program_mock_quota(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION consume_user_program_mock_quota(uuid) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION consume_user_program_mock_quota(uuid) TO service_role;


CREATE OR REPLACE FUNCTION set_user_program_exam_module(
  p_usage_id uuid,
  p_exam_module text,
  p_allow_change boolean
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  r user_program_usage;
BEGIN
  IF p_exam_module IS NULL OR p_exam_module NOT IN ('academic', 'general_training') THEN
    RAISE EXCEPTION 'invalid exam_module';
  END IF;

  -- Race-safe: only one concurrent NULL→value write wins.
  UPDATE user_program_usage
  SET
    exam_module = p_exam_module,
    updated_at = now()
  WHERE id = p_usage_id
    AND (
      exam_module IS NULL
      OR exam_module = p_exam_module
      OR (p_allow_change AND exam_module IS DISTINCT FROM p_exam_module)
    )
  RETURNING * INTO r;

  IF r.id IS NULL THEN
    RETURN NULL;
  END IF;

  RETURN to_jsonb(r);
END;
$$;

REVOKE ALL ON FUNCTION set_user_program_exam_module(uuid, text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION set_user_program_exam_module(uuid, text, boolean) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION set_user_program_exam_module(uuid, text, boolean) TO service_role;
