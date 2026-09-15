-- Society & Culture speaking mocks become student catalog Tests 1–5.
-- Park academic M01–M05 off the picker (keep L/R/W content).

-- 1) Free catalog numbers 1–5
UPDATE mock_tests
SET
  catalog_number = NULL,
  is_published = false,
  status = 'draft'
WHERE id IN (
  'a0000000-0000-4000-8000-000000000001',
  'a0000000-0000-4000-8000-000000000002',
  'a0000000-0000-4000-8000-000000000003',
  'a0000000-0000-4000-8000-000000000004',
  'a0000000-0000-4000-8000-000000000005'
);

-- 2) SC was 6–10 → 1–5
UPDATE mock_tests
SET catalog_number = catalog_number - 5
WHERE id IN (
  'a1000000-0000-4000-8000-000000000001',
  'a1000000-0000-4000-8000-000000000002',
  'a1000000-0000-4000-8000-000000000003',
  'a1000000-0000-4000-8000-000000000004',
  'a1000000-0000-4000-8000-000000000005'
)
AND catalog_number BETWEEN 6 AND 10;

-- Keep SC published
UPDATE mock_tests
SET status = 'published', is_published = true
WHERE id IN (
  'a1000000-0000-4000-8000-000000000001',
  'a1000000-0000-4000-8000-000000000002',
  'a1000000-0000-4000-8000-000000000003',
  'a1000000-0000-4000-8000-000000000004',
  'a1000000-0000-4000-8000-000000000005'
);

-- 3) Speaking Skill allotted mock → SC Community (Test 1)
UPDATE program_content_items
SET item_id = 'a1000000-0000-4000-8000-000000000001'
WHERE item_type = 'mock_test'
  AND item_id = 'a0000000-0000-4000-8000-000000000001'
  AND plan_id = (SELECT id FROM plans WHERE slug = 'speaking_skill' LIMIT 1);
