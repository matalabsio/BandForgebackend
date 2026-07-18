-- Phase 5: Expand catalogue to 4 banks × 3 sets per skill (48 hubs) and normalize submit_config.

CREATE OR REPLACE FUNCTION practice_submit_config_for_skill(sk text)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE sk
    WHEN 'writing' THEN jsonb_build_object(
      'type', 'module',
      'module', 'writing',
      'href', '/test/writing/task/1'
    )
    WHEN 'speaking' THEN jsonb_build_object(
      'type', 'module',
      'module', 'speaking',
      'href', '/test/1/speaking'
    )
    WHEN 'listening' THEN jsonb_build_object(
      'type', 'module',
      'module', 'listening',
      'href', '/test/1/listening'
    )
    WHEN 'reading' THEN jsonb_build_object(
      'type', 'module',
      'module', 'reading',
      'href', '/test/1/reading'
    )
    ELSE '{}'::jsonb
  END;
$$;

-- Backfill pilot hubs (banks 1–2) with module submit_config when empty or legacy.
UPDATE practice_hubs ph
SET submit_config = practice_submit_config_for_skill(pb.skill)
FROM practice_sets ps
JOIN practice_banks pb ON pb.id = ps.bank_id
WHERE ph.set_id = ps.id
  AND (
    ph.submit_config IS NULL
    OR ph.submit_config = '{}'::jsonb
    OR ph.submit_config ? 'submit_route'
  );

-- Full catalogue: banks 3–4 × sets 1–3 per skill.
DO $$
DECLARE
  sk text;
  b_num int;
  s_num int;
  v_bank_id uuid;
  v_set_id uuid;
  hub_slug text;
  sort_idx int;
BEGIN
  SELECT COALESCE(MAX(sort_order), 0) INTO sort_idx FROM practice_hubs;

  FOREACH sk IN ARRAY ARRAY['listening', 'reading', 'writing', 'speaking'] LOOP
    FOR b_num IN 3..4 LOOP
      SELECT id INTO v_bank_id FROM practice_banks WHERE skill = sk AND bank_number = b_num;
      IF v_bank_id IS NULL THEN
        INSERT INTO practice_banks (skill, bank_number, title, weakness_tags)
        VALUES (
          sk,
          b_num,
          initcap(sk) || ' Bank ' || b_num,
          ARRAY[sk || '_bank_' || b_num]
        )
        RETURNING id INTO v_bank_id;
      END IF;

      FOR s_num IN 1..3 LOOP
        SELECT id INTO v_set_id FROM practice_sets WHERE bank_id = v_bank_id AND set_number = s_num;
        IF v_set_id IS NULL THEN
          INSERT INTO practice_sets (bank_id, set_number, difficulty, title)
          VALUES (
            v_bank_id,
            s_num,
            CASE WHEN s_num = 1 THEN 'easy' WHEN s_num = 2 THEN 'medium' ELSE 'hard' END,
            initcap(sk) || ' Set ' || b_num || '.' || s_num
          )
          RETURNING id INTO v_set_id;
        END IF;

        sort_idx := sort_idx + 1;
        hub_slug := sk || '-b' || b_num || '-s' || s_num;

        INSERT INTO practice_hubs (
          set_id, slug, videos, practice_prompt, submit_config, estimated_min, sort_order
        )
        VALUES (
          v_set_id,
          hub_slug,
          jsonb_build_array(
            jsonb_build_object('title', initcap(sk) || ' intro', 'url', '', 'duration_min', 8)
          ),
          'Complete the ' || initcap(sk) || ' practice for bank ' || b_num || ', set ' || s_num || '.',
          practice_submit_config_for_skill(sk),
          25,
          sort_idx
        )
        ON CONFLICT (slug) DO UPDATE SET
          submit_config = EXCLUDED.submit_config,
          practice_prompt = EXCLUDED.practice_prompt,
          estimated_min = EXCLUDED.estimated_min;
      END LOOP;
    END LOOP;
  END LOOP;
END $$;

COMMENT ON FUNCTION practice_submit_config_for_skill IS
  'Phase 5: canonical module shortcut submit_config per L/R/W/S skill.';
