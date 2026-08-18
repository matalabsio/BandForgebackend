-- Phase 5: bump catalog version in the same transaction as publish/unpublish.
-- apply_practice_set_status already writes status + enqueue; a separate Python
-- bump can be lost after commit. PERFORM bump here so status, version, and
-- practice.catalog_changed succeed or roll back together.

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
  v_version bigint;
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
  v_version := NULL;

  IF (p_status = 'published') IS DISTINCT FROM (v_prev = 'published') THEN
    v_version := bump_practice_catalog_version();
  END IF;

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
    'job_id', v_job,
    'catalog_version', v_version
  );
END;
$$;

REVOKE ALL ON FUNCTION apply_practice_set_status(uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION apply_practice_set_status(uuid, text) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION apply_practice_set_status(uuid, text) TO service_role;
