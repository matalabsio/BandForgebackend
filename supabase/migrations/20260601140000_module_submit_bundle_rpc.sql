-- Phase 2b: persist answers + complete attempt + module_score in one transaction.

CREATE OR REPLACE FUNCTION persist_module_submit_bundle(
  p_attempt_id uuid,
  p_user_id uuid,
  p_completed_at timestamptz,
  p_answers jsonb,
  p_module text,
  p_score jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_attempt test_attempts%ROWTYPE;
  v_elem jsonb;
  v_qid uuid;
  v_raw integer;
  v_correct integer;
  v_total integer;
  v_band numeric;
BEGIN
  SELECT * INTO v_attempt
  FROM test_attempts
  WHERE id = p_attempt_id
    AND user_id = p_user_id
  FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'attempt_not_found';
  END IF;

  IF v_attempt.status <> 'in_progress' THEN
    RAISE EXCEPTION 'attempt_not_in_progress';
  END IF;

  IF v_attempt.module IS DISTINCT FROM p_module THEN
    RAISE EXCEPTION 'module_mismatch';
  END IF;

  FOR v_elem IN SELECT * FROM jsonb_array_elements(COALESCE(p_answers, '[]'::jsonb))
  LOOP
    v_qid := (v_elem->>'question_id')::uuid;
    INSERT INTO answers (attempt_id, question_id, user_answer, is_correct)
    VALUES (
      p_attempt_id,
      v_qid,
      COALESCE(v_elem->>'user_answer', ''),
      CASE
        WHEN v_elem ? 'is_correct' AND v_elem->>'is_correct' IS NOT NULL
        THEN (v_elem->>'is_correct')::boolean
        ELSE NULL
      END
    )
    ON CONFLICT (attempt_id, question_id)
    DO UPDATE SET
      user_answer = EXCLUDED.user_answer,
      is_correct = EXCLUDED.is_correct,
      answered_at = now();
  END LOOP;

  UPDATE test_attempts
  SET status = 'completed',
      completed_at = p_completed_at
  WHERE id = p_attempt_id;

  v_raw := NULLIF(p_score->>'raw_score', '')::integer;
  v_correct := COALESCE(
    NULLIF(p_score->>'correct_count', '')::integer,
    v_raw
  );
  v_total := NULLIF(p_score->>'total_count', '')::integer;
  v_band := NULLIF(p_score->>'band', '')::numeric;

  INSERT INTO module_scores (
    attempt_id,
    module,
    raw_score,
    correct_count,
    total_count,
    band,
    skill_breakdown
  )
  VALUES (
    p_attempt_id,
    p_module,
    v_raw,
    v_correct,
    v_total,
    v_band,
    COALESCE(p_score->'skill_breakdown', '{}'::jsonb)
  )
  ON CONFLICT (attempt_id, module)
  DO UPDATE SET
    raw_score = EXCLUDED.raw_score,
    correct_count = EXCLUDED.correct_count,
    total_count = EXCLUDED.total_count,
    band = EXCLUDED.band,
    skill_breakdown = EXCLUDED.skill_breakdown,
    scored_at = now();

  RETURN jsonb_build_object(
    'id', v_attempt.id,
    'user_id', v_attempt.user_id,
    'mock_test_id', v_attempt.mock_test_id,
    'mock_attempt_id', v_attempt.mock_attempt_id,
    'module', v_attempt.module,
    'part', v_attempt.part,
    'status', 'completed',
    'started_at', v_attempt.started_at,
    'completed_at', p_completed_at
  );
END;
$$;

REVOKE ALL ON FUNCTION persist_module_submit_bundle(uuid, uuid, timestamptz, jsonb, text, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION persist_module_submit_bundle(uuid, uuid, timestamptz, jsonb, text, jsonb) TO service_role;
