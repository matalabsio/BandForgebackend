-- Cloudflare Stream media library keyed by placement tag.

CREATE TABLE IF NOT EXISTS stream_videos (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tag text NOT NULL UNIQUE
    CHECK (tag IN (
      'bandforge-intro',
      'ielts-intro',
      'listening-intro',
      'reading-intro',
      'writing-intro',
      'speaking-intro'
    )),
  title text NOT NULL DEFAULT '',
  stream_uid text NOT NULL,
  playback_url text NOT NULL DEFAULT '',
  duration_min integer NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'ready'
    CHECK (status IN ('processing', 'ready', 'error')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_stream_videos_uid ON stream_videos (stream_uid);

ALTER TABLE stream_videos ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE stream_videos IS
  'Admin-managed Cloudflare Stream library; tag is the placement key (skill intros sync to practice_hubs.videos).';
