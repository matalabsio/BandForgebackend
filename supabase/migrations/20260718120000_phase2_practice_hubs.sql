-- Phase 2: Practice hub catalogue, user progress, per-skill full-mock unlock mapping.

CREATE TABLE IF NOT EXISTS practice_banks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  skill text NOT NULL CHECK (skill IN ('listening', 'reading', 'writing', 'speaking')),
  bank_number smallint NOT NULL CHECK (bank_number BETWEEN 1 AND 4),
  title text NOT NULL,
  weakness_tags text[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (skill, bank_number)
);

CREATE INDEX IF NOT EXISTS idx_practice_banks_skill ON practice_banks (skill);

CREATE TABLE IF NOT EXISTS practice_sets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  bank_id uuid NOT NULL REFERENCES practice_banks(id) ON DELETE CASCADE,
  set_number smallint NOT NULL CHECK (set_number BETWEEN 1 AND 3),
  difficulty text NOT NULL DEFAULT 'medium',
  title text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (bank_id, set_number)
);

CREATE TABLE IF NOT EXISTS practice_hubs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  set_id uuid NOT NULL REFERENCES practice_sets(id) ON DELETE CASCADE,
  slug text NOT NULL UNIQUE,
  videos jsonb NOT NULL DEFAULT '[]'::jsonb,
  practice_prompt text NOT NULL DEFAULT '',
  submit_config jsonb NOT NULL DEFAULT '{}'::jsonb,
  estimated_min integer NOT NULL DEFAULT 25,
  sort_order smallint NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_practice_hubs_set_id ON practice_hubs (set_id);

CREATE TABLE IF NOT EXISTS user_hub_progress (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  hub_id uuid NOT NULL REFERENCES practice_hubs(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'in_progress', 'completed')),
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, hub_id)
);

CREATE INDEX IF NOT EXISTS idx_user_hub_progress_user ON user_hub_progress (user_id);
CREATE INDEX IF NOT EXISTS idx_user_hub_progress_hub ON user_hub_progress (hub_id);

CREATE TABLE IF NOT EXISTS skill_full_mocks (
  skill text PRIMARY KEY CHECK (skill IN ('listening', 'reading', 'writing', 'speaking')),
  mock_test_id uuid NOT NULL REFERENCES mock_tests(id) ON DELETE RESTRICT,
  unlock_requires_sets smallint NOT NULL DEFAULT 12,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE practice_banks ENABLE ROW LEVEL SECURITY;
ALTER TABLE practice_sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE practice_hubs ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_hub_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE skill_full_mocks ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE practice_banks IS 'Phase 2: question banks per skill (4 banks max in full catalogue).';
COMMENT ON TABLE practice_hubs IS 'Atomic practice unit: watch + practice + submit.';
COMMENT ON TABLE user_hub_progress IS 'Per-user hub completion; drives 12/12 mock unlock.';
COMMENT ON TABLE skill_full_mocks IS 'Maps each skill to a full mock unlocked after hub progress.';

INSERT INTO skill_full_mocks (skill, mock_test_id, unlock_requires_sets)
VALUES
  ('listening', 'a0000000-0000-4000-8000-000000000001', 12),
  ('reading', 'a0000000-0000-4000-8000-000000000001', 12),
  ('writing', 'a0000000-0000-4000-8000-000000000001', 12),
  ('speaking', 'a0000000-0000-4000-8000-000000000001', 12)
ON CONFLICT (skill) DO UPDATE SET
  mock_test_id = EXCLUDED.mock_test_id,
  unlock_requires_sets = EXCLUDED.unlock_requires_sets;

-- Pilot seed: 4 skills × 2 banks × 3 sets = 24 hubs
DO $$
DECLARE
  sk text;
  b_num int;
  s_num int;
  v_bank_id uuid;
  v_set_id uuid;
  hub_slug text;
  sort_idx int := 0;
BEGIN
  FOREACH sk IN ARRAY ARRAY['listening', 'reading', 'writing', 'speaking'] LOOP
    FOR b_num IN 1..2 LOOP
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
          CASE
            WHEN sk IN ('writing', 'speaking') THEN jsonb_build_object('submit_route', '/api/' || sk)
            ELSE '{}'::jsonb
          END,
          25,
          sort_idx
        )
        ON CONFLICT (slug) DO NOTHING;
      END LOOP;
    END LOOP;
  END LOOP;
END $$;
