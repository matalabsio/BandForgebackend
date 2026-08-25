-- Speaking Skill plan foundation (inactive catalog row only).
-- Additive. Does not activate speaking_skill, attach content, or change Writing/FSP.

-- ---------------------------------------------------------------------------
-- speaking_skill plan (inactive — not purchasable until explicitly activated)
-- sort_order 11 = immediately after writing_skill (10)
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
  'speaking_skill',
  'Speaking Skill',
  'Speaking Part 1 + Part 2 + Part 3 practice hubs with one full speaking mock.',
  89900,
  'INR',
  180,
  11,
  false,
  '{
    "skills": ["speaking"],
    "mock_quota": 1,
    "personalized_plan": false,
    "inventory": {"part1": 4, "part2": 4, "part3": 4},
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
