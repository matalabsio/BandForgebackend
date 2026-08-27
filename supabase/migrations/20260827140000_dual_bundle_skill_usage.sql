-- Dual Bundle Phase 2: skill-scoped user_program_usage + inactive dual_bundle plan.
-- Additive. Does not activate dual_bundle or attach PCI to dual.

-- ---------------------------------------------------------------------------
-- 1) Skill-scoped usage (UNIQUE(subscription_id, skill))
-- ---------------------------------------------------------------------------
ALTER TABLE user_program_usage
  ADD COLUMN IF NOT EXISTS skill text;

-- Backfill from plans.slug for existing single-pack rows.
UPDATE user_program_usage u
SET skill = CASE
  WHEN p.slug = 'writing_skill' THEN 'writing'
  WHEN p.slug = 'speaking_skill' THEN 'speaking'
  ELSE 'writing'
END
FROM plans p
WHERE p.id = u.plan_id
  AND u.skill IS NULL;

UPDATE user_program_usage
SET skill = 'writing'
WHERE skill IS NULL;

ALTER TABLE user_program_usage
  ALTER COLUMN skill SET NOT NULL;

ALTER TABLE user_program_usage
  DROP CONSTRAINT IF EXISTS user_program_usage_skill_check;

ALTER TABLE user_program_usage
  ADD CONSTRAINT user_program_usage_skill_check
  CHECK (skill IN ('writing', 'speaking'));

ALTER TABLE user_program_usage
  DROP CONSTRAINT IF EXISTS user_program_usage_subscription_id_key;

-- Postgres may name the unique constraint differently depending on CREATE TABLE.
DO $$
DECLARE
  cname text;
BEGIN
  SELECT conname INTO cname
  FROM pg_constraint
  WHERE conrelid = 'user_program_usage'::regclass
    AND contype = 'u'
    AND pg_get_constraintdef(oid) = 'UNIQUE (subscription_id)';
  IF cname IS NOT NULL THEN
    EXECUTE format('ALTER TABLE user_program_usage DROP CONSTRAINT %I', cname);
  END IF;
END $$;

ALTER TABLE user_program_usage
  DROP CONSTRAINT IF EXISTS user_program_usage_subscription_skill_key;

ALTER TABLE user_program_usage
  ADD CONSTRAINT user_program_usage_subscription_skill_key
  UNIQUE (subscription_id, skill);

CREATE INDEX IF NOT EXISTS idx_user_program_usage_subscription_skill
  ON user_program_usage (subscription_id, skill);

COMMENT ON COLUMN user_program_usage.skill IS
  'Pack skill this usage row applies to (writing|speaking). Dual Bundle has two rows per subscription.';

COMMENT ON TABLE user_program_usage IS
  'Per-subscription pack usage by skill (mock quota + Writing exam_module). Dual creates one row per skill.';

-- ---------------------------------------------------------------------------
-- 2) dual_bundle plan (inactive — not purchasable until explicitly activated)
-- sort_order 12 = after speaking_skill (11)
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
  'dual_bundle',
  'Dual Bundle',
  'Writing Skill + Speaking Skill courses with one Writing mock and one Speaking mock.',
  179900,
  'INR',
  180,
  12,
  false,
  '{
    "skills": ["writing", "speaking"],
    "mock_quota": 2,
    "personalized_plan": false,
    "inventory": {
      "writing": {"task1": 6, "task2": 6},
      "speaking": {"part1": 4, "part2": 4, "part3": 4}
    },
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
