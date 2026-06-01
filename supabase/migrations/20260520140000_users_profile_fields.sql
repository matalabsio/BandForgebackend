-- Profile fields for BandForge users

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS avatar_url text,
  ADD COLUMN IF NOT EXISTS target_band numeric(2, 1);

ALTER TABLE users
  DROP CONSTRAINT IF EXISTS users_target_band_check;

ALTER TABLE users
  ADD CONSTRAINT users_target_band_check
  CHECK (target_band IS NULL OR (target_band >= 1.0 AND target_band <= 9.0));
