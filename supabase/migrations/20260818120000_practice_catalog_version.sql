-- Durable singleton version for student-visible practice catalog changes.
-- Included in personalized-plan rewrite fingerprints so publish/save
-- invalidate rewritten calendars without waiting for TTL.

CREATE TABLE IF NOT EXISTS practice_catalog_meta (
  id smallint PRIMARY KEY CHECK (id = 1),
  version bigint NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE practice_catalog_meta IS
  'Singleton: monotonically increasing version for student-visible Question Bank catalog.';

INSERT INTO practice_catalog_meta (id, version)
VALUES (1, 0)
ON CONFLICT (id) DO NOTHING;

CREATE OR REPLACE FUNCTION bump_practice_catalog_version()
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  next_version bigint;
BEGIN
  UPDATE practice_catalog_meta
     SET version = version + 1,
         updated_at = now()
   WHERE id = 1
   RETURNING version INTO next_version;
  IF next_version IS NULL THEN
    INSERT INTO practice_catalog_meta (id, version)
    VALUES (1, 1)
    ON CONFLICT (id) DO UPDATE
      SET version = practice_catalog_meta.version + 1,
          updated_at = now()
    RETURNING version INTO next_version;
  END IF;
  RETURN next_version;
END;
$$;

ALTER TABLE practice_catalog_meta ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE practice_catalog_meta FROM PUBLIC;
REVOKE ALL ON FUNCTION bump_practice_catalog_version() FROM PUBLIC;

REVOKE ALL ON TABLE practice_catalog_meta FROM anon, authenticated;
REVOKE ALL ON FUNCTION bump_practice_catalog_version() FROM anon, authenticated;

GRANT SELECT ON TABLE practice_catalog_meta TO service_role;
GRANT EXECUTE ON FUNCTION bump_practice_catalog_version() TO service_role;
