-- Phase 2: single round-trip for mock start (test row + modules + in-progress attempt).

CREATE OR REPLACE FUNCTION get_mock_start_context(
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
    )
  );
END;
$$;

REVOKE ALL ON FUNCTION get_mock_start_context(uuid, uuid, boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_mock_start_context(uuid, uuid, boolean) TO service_role;
