-- Durable full-attempt AI evaluation and atomic examiner approval/correction.
ALTER TABLE speaking_reviews
  ADD COLUMN IF NOT EXISTS evaluation_status varchar(20) NOT NULL DEFAULT 'not_queued',
  ADD COLUMN IF NOT EXISTS evaluation_attempts integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS evaluation_input_fingerprint varchar(64),
  ADD COLUMN IF NOT EXISTS evaluation_error text,
  ADD COLUMN IF NOT EXISTS evaluation_lease_token uuid,
  ADD COLUMN IF NOT EXISTS evaluation_lease_expires_at timestamptz,
  ADD COLUMN IF NOT EXISTS evaluation_next_attempt_at timestamptz,
  ADD COLUMN IF NOT EXISTS evaluation_completed_at timestamptz,
  ADD COLUMN IF NOT EXISTS approval_idempotency_key varchar(128),
  ADD COLUMN IF NOT EXISTS approval_version integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS reopened_at timestamptz,
  ADD COLUMN IF NOT EXISTS reopened_by uuid REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE speaking_reviews DROP CONSTRAINT IF EXISTS speaking_reviews_evaluation_status_check;
ALTER TABLE speaking_reviews ADD CONSTRAINT speaking_reviews_evaluation_status_check
  CHECK (evaluation_status IN ('not_queued','queued','processing','retry_wait','completed','failed'));

CREATE UNIQUE INDEX IF NOT EXISTS idx_speaking_reviews_attempt_unique
  ON speaking_reviews(attempt_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_speaking_reviews_approval_key
  ON speaking_reviews(id, approval_idempotency_key)
  WHERE approval_idempotency_key IS NOT NULL;

CREATE OR REPLACE FUNCTION claim_speaking_attempt_evaluation(
  p_review_id uuid, p_fingerprint varchar, p_lease_token uuid, p_lease_seconds integer DEFAULT 300
) RETURNS SETOF speaking_reviews
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  RETURN QUERY UPDATE speaking_reviews sr
  SET evaluation_status='processing',
      evaluation_attempts=sr.evaluation_attempts+1,
      evaluation_input_fingerprint=p_fingerprint,
      evaluation_lease_token=p_lease_token,
      evaluation_lease_expires_at=now()+make_interval(secs=>greatest(30,p_lease_seconds)),
      evaluation_error=NULL
  WHERE sr.id=p_review_id AND (
    (sr.evaluation_status IN ('not_queued','queued','retry_wait')
      AND coalesce(sr.evaluation_next_attempt_at,now())<=now())
    OR (sr.evaluation_status='processing' AND sr.evaluation_lease_expires_at<now())
    OR (sr.evaluation_status='completed' AND sr.evaluation_input_fingerprint IS DISTINCT FROM p_fingerprint)
  ) RETURNING sr.*;
END $$;
REVOKE ALL ON FUNCTION claim_speaking_attempt_evaluation(uuid,varchar,uuid,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION claim_speaking_attempt_evaluation(uuid,varchar,uuid,integer) TO service_role;

CREATE OR REPLACE FUNCTION approve_speaking_review_atomic(
  p_review_id uuid, p_admin_id uuid, p_idempotency_key varchar,
  p_scores jsonb, p_human_band numeric, p_notes text, p_override_note text,
  p_audit_metadata jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE r speaking_reviews; v_applied boolean := false;
BEGIN
  SELECT * INTO r FROM speaking_reviews WHERE id=p_review_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'review_not_found'; END IF;
  IF r.status='completed' THEN
    IF r.approval_idempotency_key=p_idempotency_key THEN
      RETURN jsonb_build_object('applied',false,'attempt_id',r.attempt_id,'version',r.approval_version);
    END IF;
    RAISE EXCEPTION 'review_completed';
  END IF;
  UPDATE speaking_reviews SET status='completed', human_band=p_human_band,
    human_criteria_scores=p_scores, reviewer_notes=p_notes, reviewer_id=p_admin_id,
    reviewed_at=now(), approval_idempotency_key=p_idempotency_key,
    approval_version=approval_version+1
  WHERE id=p_review_id RETURNING * INTO r;
  INSERT INTO module_scores(attempt_id,module,band,raw_score,correct_count,total_count,skill_breakdown)
  VALUES(r.attempt_id,'speaking',p_human_band,NULL,NULL,NULL,p_scores)
  ON CONFLICT(attempt_id,module) DO UPDATE SET band=excluded.band,skill_breakdown=excluded.skill_breakdown;
  INSERT INTO admin_audit_logs(admin_id,action,resource_type,resource_id,metadata)
  VALUES(p_admin_id,'speaking.approve','speaking_review',p_review_id::text,
    p_audit_metadata || jsonb_build_object('approval_version',r.approval_version,'override_note',p_override_note));
  v_applied := true;
  RETURN jsonb_build_object('applied',v_applied,'attempt_id',r.attempt_id,'version',r.approval_version);
END $$;
REVOKE ALL ON FUNCTION approve_speaking_review_atomic(uuid,uuid,varchar,jsonb,numeric,text,text,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION approve_speaking_review_atomic(uuid,uuid,varchar,jsonb,numeric,text,text,jsonb) TO service_role;

CREATE OR REPLACE FUNCTION reopen_speaking_review_atomic(
  p_review_id uuid, p_admin_id uuid, p_reason text
) RETURNS SETOF speaking_reviews
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE old_row speaking_reviews;
BEGIN
  SELECT * INTO old_row FROM speaking_reviews WHERE id=p_review_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'review_not_found'; END IF;
  IF old_row.status<>'completed' THEN RAISE EXCEPTION 'review_not_completed'; END IF;
  INSERT INTO admin_audit_logs(admin_id,action,resource_type,resource_id,metadata)
  VALUES(p_admin_id,'speaking.reopen','speaking_review',p_review_id::text,
    jsonb_build_object('reason',p_reason,'prior_version',old_row.approval_version,
      'prior_band',old_row.human_band,'prior_criteria',old_row.human_criteria_scores,
      'prior_notes',old_row.reviewer_notes));
  DELETE FROM module_scores WHERE attempt_id=old_row.attempt_id AND module='speaking';
  RETURN QUERY UPDATE speaking_reviews SET status='in_review', reopened_at=now(),
    reopened_by=p_admin_id, approval_idempotency_key=NULL, human_band=NULL,
    human_criteria_scores=NULL, reviewed_at=NULL
  WHERE id=p_review_id RETURNING *;
END $$;
REVOKE ALL ON FUNCTION reopen_speaking_review_atomic(uuid,uuid,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION reopen_speaking_review_atomic(uuid,uuid,text) TO service_role;
