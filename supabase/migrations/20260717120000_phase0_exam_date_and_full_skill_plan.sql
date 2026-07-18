-- Phase 0: exam date on users + diagnostic submissions; full_skill_program plan seed.

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS exam_date date;

COMMENT ON COLUMN users.exam_date IS 'IELTS exam date from diagnostic lead; drives plan timeline.';

ALTER TABLE diagnostic_review_submissions
  ADD COLUMN IF NOT EXISTS exam_date date;

COMMENT ON COLUMN diagnostic_review_submissions.exam_date IS 'Student IELTS exam date captured on diagnostic lead form.';

-- Full Skill Program (placeholder amount — update before production).
INSERT INTO plans (slug, name, description, amount, currency, duration_days, sort_order, is_active)
VALUES (
  'full_skill_program',
  'Full Skill Program',
  'All L/R/W/S practice hubs + personalised plan until your exam date.',
  100,
  'INR',
  365,
  0,
  true
)
ON CONFLICT (slug) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  is_active = true,
  sort_order = EXCLUDED.sort_order;

-- Hide legacy monthly SKUs from new checkout surfaces (rows remain for existing subs).
UPDATE plans SET is_active = false
WHERE slug IN ('starter_monthly', 'premium_monthly', 'premium_yearly')
  AND slug != 'full_skill_program';
