-- Per-set Watch explainer on Cloudflare Stream (signed playback).
ALTER TABLE practice_sets
  ADD COLUMN IF NOT EXISTS intro_video_key text,
  ADD COLUMN IF NOT EXISTS intro_stream_uid text;

COMMENT ON COLUMN practice_sets.intro_video_key IS
  'Legacy private R2 key (optional). Prefer intro_stream_uid for Stream Watch.';
COMMENT ON COLUMN practice_sets.intro_stream_uid IS
  'Cloudflare Stream UID for set Watch explainer; requireSignedURLs + short-lived tokens.';
