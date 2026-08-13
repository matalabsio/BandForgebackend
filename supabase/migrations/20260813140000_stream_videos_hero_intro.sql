-- Landing talking-head placement. Admin Videos tag hero-intro drives GET /api/marketing/hero.

ALTER TABLE stream_videos DROP CONSTRAINT IF EXISTS stream_videos_tag_check;

ALTER TABLE stream_videos
  ADD CONSTRAINT stream_videos_tag_check
  CHECK (tag IN (
    'bandforge-intro',
    'ielts-intro',
    'hero-intro',
    'listening-intro',
    'reading-intro',
    'writing-intro',
    'speaking-intro'
  ));

COMMENT ON TABLE stream_videos IS
  'Admin-managed Cloudflare Stream library; tag is the placement key (skill intros sync to practice_hubs.videos; hero-intro is the landing talking head).';
