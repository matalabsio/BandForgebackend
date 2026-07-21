-- Privacy-safe speaking-report.v2 release snapshots and response isolation.
ALTER TABLE speaking_reviews
  ADD COLUMN IF NOT EXISTS student_display_name_at_release varchar(200),
  ADD COLUMN IF NOT EXISTS student_target_band_at_release numeric(2, 1);

ALTER TABLE speaking_reviews
  DROP CONSTRAINT IF EXISTS speaking_reviews_release_target_band_check;
ALTER TABLE speaking_reviews
  ADD CONSTRAINT speaking_reviews_release_target_band_check CHECK (
    student_target_band_at_release IS NULL
    OR student_target_band_at_release BETWEEN 1.0 AND 9.0
  );

UPDATE speaking_reviews sr
SET student_display_name_at_release = COALESCE(
      sr.student_display_name_at_release,
      NULLIF(BTRIM(u.full_name), '')
    ),
    student_target_band_at_release = COALESCE(
      sr.student_target_band_at_release,
      u.target_band
    )
FROM test_attempts ta
JOIN users u ON u.id = ta.user_id
WHERE ta.id = sr.attempt_id
  AND sr.status = 'completed';

DROP POLICY IF EXISTS speaking_responses_select_own ON speaking_responses;
REVOKE ALL ON TABLE speaking_responses FROM anon, authenticated;
GRANT ALL ON TABLE speaking_responses TO service_role;

CREATE OR REPLACE FUNCTION approve_speaking_review_atomic(
  p_review_id uuid, p_admin_id uuid, p_idempotency_key varchar,
  p_request_hash varchar, p_scores jsonb, p_human_band numeric,
  p_notes text, p_override_note text, p_audit_metadata jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  r speaking_reviews;
  v_display_name varchar;
  v_credential_label varchar;
  v_student_display_name varchar;
  v_student_target_band numeric;
BEGIN
  SELECT * INTO r FROM speaking_reviews WHERE id = p_review_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'review_not_found'; END IF;
  IF r.status = 'completed' THEN
    IF r.approval_idempotency_key = p_idempotency_key THEN
      IF r.approval_request_hash IS NOT NULL
         AND r.approval_request_hash <> p_request_hash THEN
        RAISE EXCEPTION 'idempotency_payload_mismatch';
      END IF;
      RETURN jsonb_build_object(
        'applied', false,
        'attempt_id', r.attempt_id,
        'version', r.approval_version
      );
    END IF;
    RAISE EXCEPTION 'review_completed';
  END IF;

  SELECT
    COALESCE(NULLIF(BTRIM(full_name), ''), 'Certified Examiner'),
    COALESCE(
      NULLIF(BTRIM(examiner_credential_label), ''),
      'Certified IELTS Examiner'
    )
  INTO v_display_name, v_credential_label
  FROM users
  WHERE id = p_admin_id;

  SELECT NULLIF(BTRIM(u.full_name), ''), u.target_band
  INTO v_student_display_name, v_student_target_band
  FROM test_attempts ta
  JOIN users u ON u.id = ta.user_id
  WHERE ta.id = r.attempt_id;

  UPDATE speaking_reviews SET
    status = 'completed',
    human_band = p_human_band,
    human_criteria_scores = p_scores,
    reviewer_notes = p_notes,
    reviewer_id = p_admin_id,
    reviewer_display_name = COALESCE(v_display_name, 'Certified Examiner'),
    reviewer_credential_label = COALESCE(
      v_credential_label,
      'Certified IELTS Examiner'
    ),
    student_display_name_at_release = v_student_display_name,
    student_target_band_at_release = v_student_target_band,
    reviewed_at = now(),
    released_at = COALESCE(released_at, now()),
    approval_idempotency_key = p_idempotency_key,
    approval_request_hash = p_request_hash,
    approval_version = approval_version + 1
  WHERE id = p_review_id
  RETURNING * INTO r;

  INSERT INTO module_scores(
    attempt_id, module, band, raw_score, correct_count, total_count,
    skill_breakdown
  )
  VALUES(r.attempt_id, 'speaking', p_human_band, NULL, NULL, NULL, p_scores)
  ON CONFLICT(attempt_id, module) DO UPDATE
  SET band = excluded.band, skill_breakdown = excluded.skill_breakdown;

  INSERT INTO admin_audit_logs(
    admin_id, action, resource_type, resource_id, metadata
  )
  VALUES(
    p_admin_id,
    'speaking.approve',
    'speaking_review',
    p_review_id::text,
    p_audit_metadata || jsonb_build_object(
      'approval_version', r.approval_version,
      'override_note', p_override_note,
      'approval_request_hash', p_request_hash
    )
  );

  RETURN jsonb_build_object(
    'applied', true,
    'attempt_id', r.attempt_id,
    'version', r.approval_version
  );
END $$;

REVOKE ALL ON FUNCTION approve_speaking_review_atomic(
  uuid,uuid,varchar,varchar,jsonb,numeric,text,text,jsonb
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION approve_speaking_review_atomic(
  uuid,uuid,varchar,varchar,jsonb,numeric,text,text,jsonb
) TO service_role;

CREATE OR REPLACE FUNCTION reopen_speaking_review_atomic(
  p_review_id uuid, p_admin_id uuid, p_reason text
) RETURNS SETOF speaking_reviews
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE old_row speaking_reviews;
BEGIN
  SELECT * INTO old_row FROM speaking_reviews WHERE id = p_review_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'review_not_found'; END IF;
  IF old_row.status <> 'completed' THEN
    RAISE EXCEPTION 'review_not_completed';
  END IF;

  INSERT INTO admin_audit_logs(
    admin_id, action, resource_type, resource_id, metadata
  )
  VALUES(
    p_admin_id,
    'speaking.reopen',
    'speaking_review',
    p_review_id::text,
    jsonb_build_object(
      'reason', p_reason,
      'prior_version', old_row.approval_version,
      'prior_band', old_row.human_band,
      'prior_criteria', old_row.human_criteria_scores,
      'prior_notes', old_row.reviewer_notes,
      'prior_released_at', old_row.released_at
    )
  );

  DELETE FROM module_scores
  WHERE attempt_id = old_row.attempt_id AND module = 'speaking';

  RETURN QUERY UPDATE speaking_reviews SET
    status = 'in_review',
    reopened_at = now(),
    reopened_by = p_admin_id,
    approval_idempotency_key = NULL,
    approval_request_hash = NULL,
    human_band = NULL,
    human_criteria_scores = NULL,
    reviewer_notes = NULL,
    reviewer_id = NULL,
    reviewer_display_name = NULL,
    reviewer_credential_label = NULL,
    student_display_name_at_release = NULL,
    student_target_band_at_release = NULL,
    reviewed_at = NULL,
    released_at = NULL
  WHERE id = p_review_id
  RETURNING *;
END $$;

REVOKE ALL ON FUNCTION reopen_speaking_review_atomic(
  uuid,uuid,text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION reopen_speaking_review_atomic(
  uuid,uuid,text
) TO service_role;
