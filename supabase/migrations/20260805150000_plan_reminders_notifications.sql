-- Phase 6.5: plan reminder prefs + generalize notification_outbox beyond speaking.release.

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS plan_reminders_email boolean NOT NULL DEFAULT true;

-- Allow non-speaking events (learning.daily_reminder) on the same outbox.
ALTER TABLE notification_outbox
  ALTER COLUMN review_id DROP NOT NULL,
  ALTER COLUMN attempt_id DROP NOT NULL,
  ALTER COLUMN approval_version DROP NOT NULL;

ALTER TABLE notification_outbox
  ADD COLUMN IF NOT EXISTS user_id uuid REFERENCES users(id) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS idempotency_date date;

COMMENT ON COLUMN notification_outbox.idempotency_date IS
  'Local calendar date (Asia/Kolkata) for per-user daily events such as learning.daily_reminder.';

-- Idempotency: one outbox row per user + event + local date + channel.
CREATE UNIQUE INDEX IF NOT EXISTS notification_outbox_user_event_date_channel_uidx
  ON notification_outbox (user_id, event_type, idempotency_date, channel)
  WHERE user_id IS NOT NULL AND idempotency_date IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_notification_outbox_user_id
  ON notification_outbox (user_id)
  WHERE user_id IS NOT NULL;
