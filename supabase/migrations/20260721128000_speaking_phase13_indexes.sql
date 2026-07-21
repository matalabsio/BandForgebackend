-- Cover Speaking foreign keys used by deletes, review lookups, and outbox recovery.
CREATE INDEX IF NOT EXISTS idx_speaking_responses_question
  ON speaking_responses(question_id);

CREATE INDEX IF NOT EXISTS idx_speaking_reviews_reviewer
  ON speaking_reviews(reviewer_id)
  WHERE reviewer_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_speaking_reviews_reopened_by
  ON speaking_reviews(reopened_by)
  WHERE reopened_by IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_notification_outbox_review_version
  ON notification_outbox(review_id, approval_version);

CREATE INDEX IF NOT EXISTS idx_notification_outbox_attempt
  ON notification_outbox(attempt_id);
