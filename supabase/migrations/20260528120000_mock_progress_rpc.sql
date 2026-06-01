-- Single-round-trip mock progress context for orchestrator (service role only).

CREATE OR REPLACE FUNCTION get_mock_attempt_progress(
  p_mock_attempt_id uuid,
  p_user_id uuid
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_mock_test_id uuid;
  v_row jsonb;
BEGIN
  SELECT to_jsonb(ma.*)
  INTO v_row
  FROM mock_attempts ma
  WHERE ma.id = p_mock_attempt_id
    AND ma.user_id = p_user_id
  LIMIT 1;

  IF v_row IS NULL THEN
    RETURN NULL;
  END IF;

  v_mock_test_id := (v_row->>'mock_test_id')::uuid;

  RETURN jsonb_build_object(
    'mock_attempt', v_row,
    'modules', COALESCE(
      (
        SELECT jsonb_agg(to_jsonb(m) ORDER BY m.sequence_order)
        FROM mock_test_modules m
        WHERE m.mock_test_id = v_mock_test_id
      ),
      '[]'::jsonb
    ),
    'module_attempts', COALESCE(
      (
        SELECT jsonb_agg(to_jsonb(ta))
        FROM test_attempts ta
        WHERE ta.mock_attempt_id = p_mock_attempt_id
      ),
      '[]'::jsonb
    ),
    'module_scores', COALESCE(
      (
        SELECT jsonb_agg(to_jsonb(ms))
        FROM module_scores ms
        WHERE ms.attempt_id IN (
          SELECT ta.id
          FROM test_attempts ta
          WHERE ta.mock_attempt_id = p_mock_attempt_id
            AND ta.status = 'completed'
        )
      ),
      '[]'::jsonb
    )
  );
END;
$$;

REVOKE ALL ON FUNCTION get_mock_attempt_progress(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_mock_attempt_progress(uuid, uuid) TO service_role;
