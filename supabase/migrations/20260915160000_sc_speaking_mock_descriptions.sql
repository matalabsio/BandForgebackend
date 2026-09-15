-- Drop stale "Examiner videos coming soon" copy now that SC videos are on R2.

UPDATE mock_tests
SET description = CASE id
  WHEN 'a1000000-0000-4000-8000-000000000001'
    THEN 'Society & Culture speaking mock: Community. Parts 1–3 (11 questions) with examiner videos.'
  WHEN 'a1000000-0000-4000-8000-000000000002'
    THEN 'Society & Culture speaking mock: Festivals. Parts 1–3 (11 questions) with examiner videos.'
  WHEN 'a1000000-0000-4000-8000-000000000003'
    THEN 'Society & Culture speaking mock: Social Media. Parts 1–3 (11 questions) with examiner videos.'
  WHEN 'a1000000-0000-4000-8000-000000000004'
    THEN 'Society & Culture speaking mock: Media & News. Parts 1–3 (11 questions) with examiner videos.'
  WHEN 'a1000000-0000-4000-8000-000000000005'
    THEN 'Society & Culture speaking mock: Family. Parts 1–3 (11 questions) with examiner videos.'
  ELSE description
END
WHERE id IN (
  'a1000000-0000-4000-8000-000000000001',
  'a1000000-0000-4000-8000-000000000002',
  'a1000000-0000-4000-8000-000000000003',
  'a1000000-0000-4000-8000-000000000004',
  'a1000000-0000-4000-8000-000000000005'
);
