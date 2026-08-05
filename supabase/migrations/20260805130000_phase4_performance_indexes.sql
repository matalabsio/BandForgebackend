-- Phase 4: indexes for practice catalogue, progress, and exercise start
CREATE INDEX IF NOT EXISTS idx_practice_sets_status
  ON practice_sets (status);

CREATE INDEX IF NOT EXISTS idx_practice_exercise_attempts_user_hub_in_progress
  ON practice_exercise_attempts (user_id, hub_id)
  WHERE status = 'in_progress';

CREATE INDEX IF NOT EXISTS idx_user_hub_progress_user_status
  ON user_hub_progress (user_id, status);
