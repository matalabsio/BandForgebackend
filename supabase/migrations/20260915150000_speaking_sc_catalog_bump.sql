-- After Society & Culture speaking bank replace: bump catalogue so FSP plans
-- re-materialize hubs, and align speaking_skill entitlement inventory to 5×3.

SELECT bump_practice_catalog_version();

UPDATE plans
SET entitlement = jsonb_set(
  COALESCE(entitlement, '{}'::jsonb),
  '{inventory}',
  '{"part1": 5, "part2": 5, "part3": 5}'::jsonb,
  true
)
WHERE slug = 'speaking_skill';

UPDATE skill_full_mocks
SET mock_test_id = 'a1000000-0000-4000-8000-000000000001',
    unlock_requires_sets = 15
WHERE skill = 'speaking';
