-- Start gate + context in one round-trip (mock row, modules, in-progress, subscription).

CREATE OR REPLACE FUNCTION get_mock_start_gate_context(
  p_user_id uuid,
  p_mock_test_id uuid,
  p_allow_unpublished boolean DEFAULT false
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_test jsonb;
  v_has_sub boolean;
BEGIN
  SELECT to_jsonb(mt.*)
  INTO v_test
  FROM mock_tests mt
  WHERE mt.id = p_mock_test_id
    AND (mt.is_published OR p_allow_unpublished)
  LIMIT 1;

  IF v_test IS NULL THEN
    RETURN NULL;
  END IF;

  SELECT EXISTS (
    SELECT 1
    FROM subscriptions s
    WHERE s.user_id = p_user_id
      AND s.status = 'active'
      AND s.expires_at > now()
  )
  INTO v_has_sub;

  RETURN jsonb_build_object(
    'mock_test', v_test,
    'modules', COALESCE(
      (
        SELECT jsonb_agg(to_jsonb(m) ORDER BY m.sequence_order)
        FROM mock_test_modules m
        WHERE m.mock_test_id = p_mock_test_id
      ),
      '[]'::jsonb
    ),
    'in_progress_attempt', (
      SELECT to_jsonb(ma)
      FROM mock_attempts ma
      WHERE ma.user_id = p_user_id
        AND ma.mock_test_id = p_mock_test_id
        AND ma.status = 'in_progress'
      LIMIT 1
    ),
    'has_active_subscription', COALESCE(v_has_sub, false)
  );
END;
$$;

REVOKE ALL ON FUNCTION get_mock_start_gate_context(uuid, uuid, boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_mock_start_gate_context(uuid, uuid, boolean) TO service_role;
