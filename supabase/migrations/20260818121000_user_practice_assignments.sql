-- Durable per-user Question Bank assignment ledger.
-- A row means the user was assigned this set/hub (not merely that they
-- completed it). History must survive unpublish/archive, so hub/set FKs
-- are RESTRICT rather than CASCADE.

CREATE TABLE IF NOT EXISTS user_practice_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  hub_id uuid NOT NULL REFERENCES practice_hubs(id) ON DELETE RESTRICT,
  practice_set_id uuid NOT NULL REFERENCES practice_sets(id) ON DELETE RESTRICT,
  skill text NOT NULL CHECK (skill IN ('listening', 'reading', 'writing', 'speaking')),
  assigned_on date NOT NULL,
  source text NOT NULL CHECK (
    source IN ('plan_generate', 'publish_fill', 'replan', 'serve_fill')
  ),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, hub_id),
  UNIQUE (user_id, practice_set_id)
);

CREATE INDEX IF NOT EXISTS idx_user_practice_assignments_user_skill
  ON user_practice_assignments (user_id, skill);

COMMENT ON TABLE user_practice_assignments IS
  'Durable Question Bank assignments for personalized plans. Unique per user+set and user+hub. Not completion history.';

ALTER TABLE user_practice_assignments ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE user_practice_assignments FROM PUBLIC;
REVOKE ALL ON TABLE user_practice_assignments FROM anon, authenticated;
GRANT SELECT, INSERT ON TABLE user_practice_assignments TO service_role;

-- Idempotent backfill from current plans, hub progress, and exercise attempts.
-- Question Bank hubs only (custom bank 5+, bank submit_config, or bank_sections).
-- ON CONFLICT DO NOTHING so reruns never replace existing rows.
CREATE OR REPLACE FUNCTION backfill_user_practice_assignments()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  n integer := 0;
BEGIN
  WITH qb_hubs AS (
    SELECT
      ph.id AS hub_id,
      ph.set_id AS practice_set_id,
      pb.skill
    FROM practice_hubs ph
    JOIN practice_sets ps ON ps.id = ph.set_id
    JOIN practice_banks pb ON pb.id = ps.bank_id
    WHERE pb.bank_number >= 5
       OR COALESCE(ph.submit_config->>'type', '') = 'bank'
       OR EXISTS (
            SELECT 1 FROM bank_sections bs WHERE bs.practice_set_id = ph.set_id
          )
  ),
  from_plan AS (
    SELECT
      ulp.user_id,
      qh.hub_id,
      qh.practice_set_id,
      qh.skill,
      COALESCE(NULLIF(ulp.study_plan->>'prep_start', '')::date, CURRENT_DATE) AS assigned_on,
      'plan_generate'::text AS source
    FROM user_learning_profiles ulp
    CROSS JOIN LATERAL (
      SELECT DISTINCT x.hub_id
      FROM (
        SELECT jsonb_array_elements_text(
          COALESCE(ulp.study_plan->'assigned_hub_ids', '[]'::jsonb)
        ) AS hub_id
        UNION
        SELECT t->>'hub_id'
        FROM jsonb_array_elements(COALESCE(ulp.study_plan->'weeks', '[]'::jsonb)) AS w,
             jsonb_array_elements(COALESCE(w->'days', '[]'::jsonb)) AS d,
             jsonb_array_elements(COALESCE(d->'tasks', '[]'::jsonb)) AS t
        WHERE NULLIF(t->>'hub_id', '') IS NOT NULL
      ) x
      WHERE x.hub_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    ) ids
    JOIN qb_hubs qh ON qh.hub_id = ids.hub_id::uuid
  ),
  from_progress AS (
    SELECT
      uhp.user_id,
      qh.hub_id,
      qh.practice_set_id,
      qh.skill,
      COALESCE(uhp.completed_at::date, uhp.created_at::date, CURRENT_DATE) AS assigned_on,
      'serve_fill'::text AS source
    FROM user_hub_progress uhp
    JOIN qb_hubs qh ON qh.hub_id = uhp.hub_id
  ),
  from_attempts AS (
    SELECT
      pea.user_id,
      qh.hub_id,
      qh.practice_set_id,
      qh.skill,
      COALESCE(pea.started_at::date, pea.created_at::date, CURRENT_DATE) AS assigned_on,
      'serve_fill'::text AS source
    FROM practice_exercise_attempts pea
    JOIN qb_hubs qh ON qh.hub_id = pea.hub_id
  ),
  combined AS (
    SELECT DISTINCT ON (user_id, practice_set_id)
      user_id,
      hub_id,
      practice_set_id,
      skill,
      assigned_on,
      source
    FROM (
      SELECT DISTINCT ON (user_id, hub_id)
        user_id,
        hub_id,
        practice_set_id,
        skill,
        assigned_on,
        source
      FROM (
        SELECT * FROM from_plan
        UNION ALL
        SELECT * FROM from_progress
        UNION ALL
        SELECT * FROM from_attempts
      ) src
      ORDER BY user_id, hub_id, source ASC, assigned_on ASC
    ) per_hub
    ORDER BY user_id, practice_set_id, source ASC, assigned_on ASC
  )
  INSERT INTO user_practice_assignments (
    user_id, hub_id, practice_set_id, skill, assigned_on, source
  )
  SELECT user_id, hub_id, practice_set_id, skill, assigned_on, source
  FROM combined
  ON CONFLICT DO NOTHING;

  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$$;

REVOKE ALL ON FUNCTION backfill_user_practice_assignments() FROM PUBLIC;
REVOKE ALL ON FUNCTION backfill_user_practice_assignments() FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION backfill_user_practice_assignments() TO service_role;

SELECT backfill_user_practice_assignments();
