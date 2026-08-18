-- Allow admin (service_role) to remove assignment ledger rows when deleting
-- a custom practice set. History still survives unpublish/archive; only
-- explicit set delete clears these RESTRICT FKs.

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE user_practice_assignments TO service_role;
