-- Phase 9: Adaptive learning profiles (aggregates + rule-based study plans).
-- Backend uses service_role (bypasses RLS). Students read/update via FastAPI only.

CREATE TABLE IF NOT EXISTS user_learning_profiles (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  current_band numeric(3, 1),
  target_band numeric(3, 1),
  module_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  criterion_trends jsonb NOT NULL DEFAULT '{}'::jsonb,
  skill_weaknesses jsonb NOT NULL DEFAULT '[]'::jsonb,
  top_weaknesses jsonb NOT NULL DEFAULT '[]'::jsonb,
  vocab_stats jsonb NOT NULL DEFAULT '{}'::jsonb,
  grammar_stats jsonb NOT NULL DEFAULT '{}'::jsonb,
  recommendations jsonb NOT NULL DEFAULT '[]'::jsonb,
  study_plan jsonb NOT NULL DEFAULT '{}'::jsonb,
  weekly_goals jsonb NOT NULL DEFAULT '[]'::jsonb,
  source_counts jsonb NOT NULL DEFAULT '{}'::jsonb,
  refreshed_at timestamptz,
  plan_week_start date,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_learning_profiles_refreshed_at
  ON user_learning_profiles (refreshed_at);

COMMENT ON TABLE user_learning_profiles IS
  'Phase 9 adaptive learning profile: weakness aggregates, trends, rule-based plan.';

ALTER TABLE user_learning_profiles ENABLE ROW LEVEL SECURITY;

-- No client policies — service_role only (matches payments pattern).
