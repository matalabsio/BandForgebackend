-- Phase 1: personalized study plan metadata on learning profiles
ALTER TABLE user_learning_profiles
  ADD COLUMN IF NOT EXISTS prep_start date,
  ADD COLUMN IF NOT EXISTS exam_date date,
  ADD COLUMN IF NOT EXISTS total_days integer,
  ADD COLUMN IF NOT EXISTS plan_tier text,
  ADD COLUMN IF NOT EXISTS skill_difficulty jsonb DEFAULT '{}'::jsonb;
