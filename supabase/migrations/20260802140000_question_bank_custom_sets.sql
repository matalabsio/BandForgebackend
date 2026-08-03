-- Allow custom named practice sets (Question Bank create) beyond catalog 4×3.

ALTER TABLE practice_banks DROP CONSTRAINT IF EXISTS practice_banks_bank_number_check;
ALTER TABLE practice_banks
  ADD CONSTRAINT practice_banks_bank_number_check CHECK (bank_number >= 1);

ALTER TABLE practice_sets DROP CONSTRAINT IF EXISTS practice_sets_set_number_check;
ALTER TABLE practice_sets
  ADD CONSTRAINT practice_sets_set_number_check CHECK (set_number >= 1);

ALTER TABLE practice_sets
  ADD COLUMN IF NOT EXISTS description text,
  ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'draft',
  ADD COLUMN IF NOT EXISTS created_by uuid REFERENCES users(id) ON DELETE SET NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'practice_sets_status_check'
  ) THEN
    ALTER TABLE practice_sets
      ADD CONSTRAINT practice_sets_status_check
      CHECK (status IN ('draft', 'published', 'archived'));
  END IF;
END $$;

COMMENT ON COLUMN practice_sets.description IS
  'Optional admin description for custom / catalog practice sets.';
COMMENT ON COLUMN practice_sets.status IS
  'draft | published | archived — used by Question Bank create flow.';
