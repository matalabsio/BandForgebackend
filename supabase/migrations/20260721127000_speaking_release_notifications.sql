-- Phase 13: durable, consent-aware Speaking release notifications.
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS speaking_release_email_enabled boolean NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS speaking_release_whatsapp_enabled boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS speaking_release_whatsapp_consented_at timestamptz,
  ADD COLUMN IF NOT EXISTS speaking_release_whatsapp_consent_version varchar(80);

CREATE OR REPLACE FUNCTION invalidate_whatsapp_consent_on_phone_change()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
  IF NEW.phone IS DISTINCT FROM OLD.phone THEN
    NEW.phone_verified_at := NULL;
    NEW.speaking_release_whatsapp_enabled := false;
    -- Retain consent timestamp/version as audit evidence, but it is no longer eligible.
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS users_invalidate_whatsapp_consent_on_phone_change ON users;
CREATE TRIGGER users_invalidate_whatsapp_consent_on_phone_change
BEFORE UPDATE OF phone ON users
FOR EACH ROW EXECUTE FUNCTION invalidate_whatsapp_consent_on_phone_change();

CREATE TABLE IF NOT EXISTS notification_outbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type varchar(80) NOT NULL,
  review_id uuid NOT NULL REFERENCES speaking_reviews(id) ON DELETE CASCADE,
  attempt_id uuid NOT NULL REFERENCES test_attempts(id) ON DELETE CASCADE,
  approval_version integer NOT NULL CHECK (approval_version > 0),
  channel varchar(20) NOT NULL CHECK (channel IN ('email', 'whatsapp')),
  recipient_snapshot text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  template_version varchar(80) NOT NULL,
  status varchar(20) NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued','processing','retry','sent','delivered','read','failed','cancelled')),
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  max_attempts integer NOT NULL DEFAULT 6 CHECK (max_attempts BETWEEN 1 AND 20),
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  lease_token uuid,
  lease_expires_at timestamptz,
  provider_message_id text,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz,
  delivered_at timestamptz,
  read_at timestamptz,
  failed_at timestamptz,
  cancelled_at timestamptz,
  UNIQUE(event_type, review_id, approval_version, channel)
);

CREATE INDEX IF NOT EXISTS notification_outbox_claim_idx
  ON notification_outbox(next_attempt_at, created_at)
  WHERE status IN ('queued', 'retry', 'processing');
CREATE UNIQUE INDEX IF NOT EXISTS notification_outbox_provider_message_uidx
  ON notification_outbox(provider_message_id) WHERE provider_message_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS notification_delivery_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider varchar(30) NOT NULL,
  provider_event_id text NOT NULL,
  provider_message_id text,
  status varchar(20) NOT NULL,
  occurred_at timestamptz,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(provider, provider_event_id)
);

ALTER TABLE notification_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_delivery_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE notification_outbox, notification_delivery_events FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE notification_outbox, notification_delivery_events TO service_role;

CREATE OR REPLACE FUNCTION claim_notification_outbox(
  p_batch_size integer DEFAULT 20,
  p_lease_seconds integer DEFAULT 120
) RETURNS SETOF notification_outbox
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  RETURN QUERY
  WITH candidates AS (
    SELECT id
    FROM notification_outbox
    WHERE (
      status IN ('queued', 'retry') AND next_attempt_at <= now()
    ) OR (
      status = 'processing' AND lease_expires_at < now()
    )
    ORDER BY next_attempt_at, created_at
    FOR UPDATE SKIP LOCKED
    LIMIT LEAST(GREATEST(p_batch_size, 1), 100)
  )
  UPDATE notification_outbox o
  SET status = 'processing',
      attempts = o.attempts + 1,
      lease_token = gen_random_uuid(),
      lease_expires_at = now() + make_interval(secs => LEAST(GREATEST(p_lease_seconds, 15), 900))
  FROM candidates c
  WHERE o.id = c.id
  RETURNING o.*;
END $$;
REVOKE ALL ON FUNCTION claim_notification_outbox(integer, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION claim_notification_outbox(integer, integer) TO service_role;

CREATE OR REPLACE FUNCTION record_notification_delivery_event(
  p_provider varchar,
  p_provider_event_id text,
  p_provider_message_id text,
  p_status varchar,
  p_occurred_at timestamptz,
  p_payload jsonb
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_event_id uuid;
  v_timestamp timestamptz := COALESCE(p_occurred_at, now());
BEGIN
  INSERT INTO notification_delivery_events(
    provider, provider_event_id, provider_message_id, status, occurred_at, payload
  ) VALUES (
    p_provider, p_provider_event_id, p_provider_message_id, p_status,
    p_occurred_at, COALESCE(p_payload, '{}'::jsonb)
  )
  ON CONFLICT(provider, provider_event_id) DO NOTHING
  RETURNING id INTO v_event_id;

  IF v_event_id IS NULL THEN
    RETURN false;
  END IF;

  IF p_status = 'sent' THEN
    UPDATE notification_outbox SET status='sent', sent_at=v_timestamp
    WHERE provider_message_id=p_provider_message_id AND status='sent';
  ELSIF p_status = 'delivered' THEN
    UPDATE notification_outbox SET status='delivered', delivered_at=v_timestamp
    WHERE provider_message_id=p_provider_message_id AND status IN ('sent','delivered');
  ELSIF p_status = 'read' THEN
    UPDATE notification_outbox SET status='read', read_at=v_timestamp
    WHERE provider_message_id=p_provider_message_id AND status IN ('sent','delivered','read');
  ELSIF p_status = 'failed' THEN
    UPDATE notification_outbox SET status='failed', failed_at=v_timestamp
    WHERE provider_message_id=p_provider_message_id AND status IN ('sent','failed');
  END IF;

  RETURN true;
END $$;
REVOKE ALL ON FUNCTION record_notification_delivery_event(
  varchar,text,text,varchar,timestamptz,jsonb
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION record_notification_delivery_event(
  varchar,text,text,varchar,timestamptz,jsonb
) TO service_role;

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
  v_owner users;
  v_test_number integer;
BEGIN
  SELECT * INTO r FROM speaking_reviews WHERE id = p_review_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'review_not_found'; END IF;
  IF r.status = 'completed' THEN
    IF r.approval_idempotency_key = p_idempotency_key THEN
      IF r.approval_request_hash IS NOT NULL AND r.approval_request_hash <> p_request_hash THEN
        RAISE EXCEPTION 'idempotency_payload_mismatch';
      END IF;
      RETURN jsonb_build_object('applied', false, 'attempt_id', r.attempt_id, 'version', r.approval_version);
    END IF;
    RAISE EXCEPTION 'review_completed';
  END IF;

  SELECT COALESCE(NULLIF(BTRIM(full_name), ''), 'Certified Examiner'),
         COALESCE(NULLIF(BTRIM(examiner_credential_label), ''), 'Certified IELTS Examiner')
  INTO v_display_name, v_credential_label FROM users WHERE id = p_admin_id;

  SELECT u.* INTO v_owner
  FROM test_attempts ta
  JOIN users u ON u.id = ta.user_id
  WHERE ta.id = r.attempt_id FOR SHARE OF u;

  SELECT mt.catalog_number INTO v_test_number
  FROM test_attempts ta
  LEFT JOIN mock_tests mt ON mt.id = ta.mock_test_id
  WHERE ta.id = r.attempt_id;

  v_student_display_name := NULLIF(BTRIM(v_owner.full_name), '');
  v_student_target_band := v_owner.target_band;

  UPDATE speaking_reviews SET
    status='completed', human_band=p_human_band, human_criteria_scores=p_scores,
    reviewer_notes=p_notes, reviewer_id=p_admin_id,
    reviewer_display_name=COALESCE(v_display_name, 'Certified Examiner'),
    reviewer_credential_label=COALESCE(v_credential_label, 'Certified IELTS Examiner'),
    student_display_name_at_release=v_student_display_name,
    student_target_band_at_release=v_student_target_band,
    reviewed_at=now(), released_at=COALESCE(released_at, now()),
    approval_idempotency_key=p_idempotency_key, approval_request_hash=p_request_hash,
    approval_version=approval_version + 1
  WHERE id=p_review_id RETURNING * INTO r;

  INSERT INTO module_scores(attempt_id,module,band,raw_score,correct_count,total_count,skill_breakdown)
  VALUES(r.attempt_id,'speaking',p_human_band,NULL,NULL,NULL,p_scores)
  ON CONFLICT(attempt_id,module) DO UPDATE SET band=excluded.band,skill_breakdown=excluded.skill_breakdown;

  INSERT INTO admin_audit_logs(admin_id,action,resource_type,resource_id,metadata)
  VALUES(p_admin_id,'speaking.approve','speaking_review',p_review_id::text,
    p_audit_metadata || jsonb_build_object('approval_version',r.approval_version,
      'override_note',p_override_note,'approval_request_hash',p_request_hash));

  IF v_owner.speaking_release_email_enabled AND NULLIF(BTRIM(v_owner.email), '') IS NOT NULL THEN
    INSERT INTO notification_outbox(
      event_type,review_id,attempt_id,approval_version,channel,recipient_snapshot,payload,template_version
    ) VALUES (
      'speaking.release',r.id,r.attempt_id,r.approval_version,'email',LOWER(BTRIM(v_owner.email)),
      jsonb_build_object('student_name',v_student_display_name,
        'examiner_name',r.reviewer_display_name,'test_number',v_test_number),
      'speaking_release_email_v1'
    ) ON CONFLICT(event_type,review_id,approval_version,channel) DO NOTHING;
  END IF;

  IF v_owner.speaking_release_whatsapp_enabled
     AND NULLIF(BTRIM(v_owner.phone), '') IS NOT NULL
     AND v_owner.phone_verified_at IS NOT NULL
     AND v_owner.speaking_release_whatsapp_consented_at IS NOT NULL
     AND v_owner.speaking_release_whatsapp_consent_version = 'speaking_release_whatsapp_v1' THEN
    INSERT INTO notification_outbox(
      event_type,review_id,attempt_id,approval_version,channel,recipient_snapshot,payload,template_version
    ) VALUES (
      'speaking.release',r.id,r.attempt_id,r.approval_version,'whatsapp',BTRIM(v_owner.phone),
      jsonb_build_object('student_name',v_student_display_name,'test_number',v_test_number),
      'speaking_release_whatsapp_v1'
    ) ON CONFLICT(event_type,review_id,approval_version,channel) DO NOTHING;
  END IF;

  RETURN jsonb_build_object('applied',true,'attempt_id',r.attempt_id,'version',r.approval_version);
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
  SELECT * INTO old_row FROM speaking_reviews WHERE id=p_review_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'review_not_found'; END IF;
  IF old_row.status <> 'completed' THEN RAISE EXCEPTION 'review_not_completed'; END IF;

  UPDATE notification_outbox SET status='cancelled', cancelled_at=now(),
    lease_token=NULL, lease_expires_at=NULL
  WHERE review_id=p_review_id AND approval_version=old_row.approval_version
    AND status IN ('queued','retry','processing');

  INSERT INTO admin_audit_logs(admin_id,action,resource_type,resource_id,metadata)
  VALUES(p_admin_id,'speaking.reopen','speaking_review',p_review_id::text,
    jsonb_build_object('reason',p_reason,'prior_version',old_row.approval_version,
      'prior_band',old_row.human_band,'prior_criteria',old_row.human_criteria_scores,
      'prior_notes',old_row.reviewer_notes,'prior_released_at',old_row.released_at));
  DELETE FROM module_scores WHERE attempt_id=old_row.attempt_id AND module='speaking';

  RETURN QUERY UPDATE speaking_reviews SET
    status='in_review',reopened_at=now(),reopened_by=p_admin_id,
    approval_idempotency_key=NULL,approval_request_hash=NULL,human_band=NULL,
    human_criteria_scores=NULL,reviewer_notes=NULL,reviewer_id=NULL,
    reviewer_display_name=NULL,reviewer_credential_label=NULL,
    student_display_name_at_release=NULL,student_target_band_at_release=NULL,
    reviewed_at=NULL,released_at=NULL
  WHERE id=p_review_id RETURNING *;
END $$;
REVOKE ALL ON FUNCTION reopen_speaking_review_atomic(uuid,uuid,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION reopen_speaking_review_atomic(uuid,uuid,text) TO service_role;
