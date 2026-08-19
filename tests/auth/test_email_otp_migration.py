from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260819051555_email_otp_verifications.sql"
)

RPC_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260819055111_email_otp_increment_attempt_rpc.sql"
)


def _sql() -> str:
    return MIGRATION.read_text()


def _rpc_sql() -> str:
    return RPC_MIGRATION.read_text()


def test_email_otp_table_sql_has_required_columns():
    sql = _sql()
    for column in (
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid()",
        "email text NOT NULL",
        "code_hash text NOT NULL",
        "purpose text NOT NULL DEFAULT 'login'",
        "attempts int NOT NULL DEFAULT 0",
        "max_attempts int NOT NULL DEFAULT 5",
        "expires_at timestamptz NOT NULL",
        "consumed_at timestamptz",
        "created_at timestamptz NOT NULL DEFAULT now()",
    ):
        assert column in sql
    assert "CREATE TABLE IF NOT EXISTS email_otp_verifications" in sql
    assert "ALTER TABLE otp_verifications" not in sql
    assert "CREATE TABLE IF NOT EXISTS otp_verifications" not in sql


def test_email_otp_defaults_match_phone_otp():
    sql = _sql()
    assert "purpose text NOT NULL DEFAULT 'login'" in sql
    assert "attempts int NOT NULL DEFAULT 0" in sql
    assert "max_attempts int NOT NULL DEFAULT 5" in sql


def test_email_otp_email_normalization_check():
    sql = _sql()
    assert "CHECK (email = lower(btrim(email)) AND length(email) > 0)" in sql


def test_email_otp_lookup_and_expiry_indexes():
    sql = _sql()
    assert (
        "CREATE INDEX IF NOT EXISTS idx_email_otp_email_purpose ON email_otp_verifications (email, purpose)"
        in sql
    )
    assert (
        "CREATE INDEX IF NOT EXISTS idx_email_otp_expires ON email_otp_verifications (expires_at)"
        in sql
    )


def test_email_otp_rls_enabled_without_client_policies():
    sql = _rpc_sql()
    assert "ALTER TABLE email_otp_verifications ENABLE ROW LEVEL SECURITY" in sql
    assert "CREATE POLICY" not in sql
    assert "REVOKE ALL ON TABLE email_otp_verifications FROM anon, authenticated" in sql
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE email_otp_verifications TO service_role" in sql


def test_email_otp_increment_attempt_rpc_is_atomic_and_service_role_only():
    sql = _rpc_sql()
    assert "CREATE OR REPLACE FUNCTION increment_email_otp_attempt" in sql
    assert "attempts = attempts + 1" in sql
    assert "AND attempts < max_attempts" in sql
    assert "GRANT EXECUTE ON FUNCTION public.increment_email_otp_attempt(uuid) TO service_role" in sql
    assert "REVOKE EXECUTE ON FUNCTION public.increment_email_otp_attempt(uuid) FROM anon, authenticated" in sql


def test_email_otp_create_rpc_is_atomic_and_service_role_only():
    sql = _rpc_sql()
    assert "CREATE OR REPLACE FUNCTION create_email_otp_verification" in sql
    assert "pg_advisory_xact_lock(hashtext(p_email || '|' || p_purpose))" in sql
    assert "p_code_hash" in sql
    assert "GRANT EXECUTE ON FUNCTION public.create_email_otp_verification" in sql
    assert "REVOKE EXECUTE ON FUNCTION public.create_email_otp_verification" in sql
    assert "FROM anon, authenticated" in sql
