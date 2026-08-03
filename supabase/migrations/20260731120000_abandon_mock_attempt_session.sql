-- Batch-abandon in-progress module attempts (and optionally the parent mock session).

CREATE OR REPLACE FUNCTION abandon_mock_attempt_children(p_mock_attempt_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE test_attempts
  SET status = 'abandoned'
  WHERE mock_attempt_id = p_mock_attempt_id
    AND status = 'in_progress';
END;
$$;

CREATE OR REPLACE FUNCTION abandon_mock_attempt_session(p_mock_attempt_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE test_attempts
  SET status = 'abandoned'
  WHERE mock_attempt_id = p_mock_attempt_id
    AND status = 'in_progress';

  UPDATE mock_attempts
  SET status = 'abandoned'
  WHERE id = p_mock_attempt_id
    AND status = 'in_progress';
END;
$$;

REVOKE ALL ON FUNCTION abandon_mock_attempt_children(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION abandon_mock_attempt_children(uuid) TO service_role;

REVOKE ALL ON FUNCTION abandon_mock_attempt_session(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION abandon_mock_attempt_session(uuid) TO service_role;
