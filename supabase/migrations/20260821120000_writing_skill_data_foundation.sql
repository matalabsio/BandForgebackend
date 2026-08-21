-- Phase 2: Writing Skill data foundation (inactive plan + module tags + program tables).
-- Additive only. Does not activate writing_skill, attach content, or change FSP.

-- ---------------------------------------------------------------------------
-- plans.entitlement (metadata only; PLAN_SKILL_GRANTS remains auth SoT)
-- ---------------------------------------------------------------------------
ALTER TABLE plans
  ADD COLUMN IF NOT EXISTS entitlement jsonb;

COMMENT ON COLUMN plans.entitlement IS
  'Catalog metadata for pack SKUs (skills, mock_quota, inventory). Not used for authorization.';

-- ---------------------------------------------------------------------------
-- writing_skill plan (inactive — not purchasable until explicitly activated)
-- ---------------------------------------------------------------------------
INSERT INTO plans (
  slug,
  name,
  description,
  amount,
  currency,
  duration_days,
  sort_order,
  is_active,
  entitlement
)
VALUES (
  'writing_skill',
  'Writing Skill',
  'Writing Task 1 + Task 2 practice hubs with one full writing mock.',
  89900,
  'INR',
  180,
  10,
  false,
  '{
    "skills": ["writing"],
    "mock_quota": 1,
    "personalized_plan": false,
    "inventory": {"task1": 6, "task2": 6},
    "sequential": true
  }'::jsonb
)
ON CONFLICT (slug) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  amount = EXCLUDED.amount,
  currency = EXCLUDED.currency,
  duration_days = EXCLUDED.duration_days,
  sort_order = EXCLUDED.sort_order,
  is_active = false,
  entitlement = EXCLUDED.entitlement;

-- ---------------------------------------------------------------------------
-- users.exam_module (nullable; existing users stay unset)
-- ---------------------------------------------------------------------------
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS exam_module text;

ALTER TABLE users
  DROP CONSTRAINT IF EXISTS users_exam_module_check;

ALTER TABLE users
  ADD CONSTRAINT users_exam_module_check
  CHECK (
    exam_module IS NULL
    OR exam_module IN ('academic', 'general_training')
  );

COMMENT ON COLUMN users.exam_module IS
  'IELTS exam track for content routing: academic | general_training. Nullable until user confirms.';

-- ---------------------------------------------------------------------------
-- practice_sets.exam_module (nullable; backfill writing only)
-- ---------------------------------------------------------------------------
ALTER TABLE practice_sets
  ADD COLUMN IF NOT EXISTS exam_module text;

ALTER TABLE practice_sets
  DROP CONSTRAINT IF EXISTS practice_sets_exam_module_check;

ALTER TABLE practice_sets
  ADD CONSTRAINT practice_sets_exam_module_check
  CHECK (
    exam_module IS NULL
    OR exam_module IN ('academic', 'general_training', 'both')
  );

COMMENT ON COLUMN practice_sets.exam_module IS
  'Content track tag: academic | general_training | both. NULL = untagged (not pack-routed).';

-- Safe backfill: current writing bank content is Academic Task 1 / shared Task 2 only.
-- Do not tag listening/reading/speaking sets.
UPDATE practice_sets ps
SET exam_module = 'academic'
FROM practice_banks pb
WHERE ps.bank_id = pb.id
  AND pb.skill = 'writing'
  AND ps.exam_module IS NULL;

CREATE INDEX IF NOT EXISTS idx_practice_sets_exam_module_status
  ON practice_sets (exam_module, status)
  WHERE exam_module IS NOT NULL;

-- ---------------------------------------------------------------------------
-- program_content_items (SKU ↔ hub/mock membership; empty until composer)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS program_content_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  plan_id uuid NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  item_type text NOT NULL
    CHECK (item_type IN ('practice_hub', 'mock_test')),
  item_id uuid NOT NULL,
  exam_module text NOT NULL
    CHECK (exam_module IN ('academic', 'general_training', 'both')),
  sort_order smallint NOT NULL DEFAULT 0,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (plan_id, item_type, item_id, exam_module)
);

CREATE INDEX IF NOT EXISTS idx_program_content_items_plan_module_sort
  ON program_content_items (plan_id, exam_module, sort_order);

CREATE INDEX IF NOT EXISTS idx_program_content_items_item
  ON program_content_items (item_type, item_id);

COMMENT ON TABLE program_content_items IS
  'Program SKU content membership (practice hubs / mocks) by exam_module. Empty until admin attaches inventory.';

ALTER TABLE program_content_items ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE program_content_items FROM PUBLIC;
REVOKE ALL ON TABLE program_content_items FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE program_content_items TO service_role;

-- ---------------------------------------------------------------------------
-- user_program_usage (per purchase usage; no fulfillment wiring yet)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_program_usage (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  subscription_id uuid NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
  plan_id uuid NOT NULL REFERENCES plans(id) ON DELETE RESTRICT,
  exam_module text
    CHECK (
      exam_module IS NULL
      OR exam_module IN ('academic', 'general_training')
    ),
  mocks_granted integer NOT NULL DEFAULT 1
    CHECK (mocks_granted >= 0),
  mocks_used integer NOT NULL DEFAULT 0
    CHECK (mocks_used >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (subscription_id),
  CONSTRAINT user_program_usage_mocks_within_grant
    CHECK (mocks_used <= mocks_granted)
);

CREATE INDEX IF NOT EXISTS idx_user_program_usage_user
  ON user_program_usage (user_id);

CREATE INDEX IF NOT EXISTS idx_user_program_usage_user_plan
  ON user_program_usage (user_id, plan_id);

COMMENT ON TABLE user_program_usage IS
  'Per-subscription pack usage (mock quota snapshot). Created at fulfillment (not wired in Phase 2).';

ALTER TABLE user_program_usage ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE user_program_usage FROM PUBLIC;
REVOKE ALL ON TABLE user_program_usage FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE user_program_usage TO service_role;
