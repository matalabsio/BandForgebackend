# Tier 1 PII masking (non-prod)

Automatic anonymization of contact + auth secrets after every **non-production** DB refresh, with triggers that keep masking **new writes** while enabled.

**Do not enable on production.** The migration ships with `pii_masking_config.enabled = false`. Scripts refuse the primary production project ref by default.

## What is masked (Tier 1)

| Table | Columns |
|---|---|
| `users` | `email`, `phone`, `full_name`, `password_hash` |
| `signup_leads` | `email`, `phone`, `full_name` |
| `diagnostic_review_submissions` | `email`, `phone`, `full_name` |
| `otp_verifications` | `phone`, `code_hash` |
| `email_otp_verifications` | `email`, `code_hash` |
| `notification_outbox` | `recipient_snapshot` |
| `password_reset_tokens` | `token_hash` |
| `refresh_sessions` | `token_hash`, `ip_address`, `user_agent` |

Fake values are deterministic from row `id` (unique-safe):

- email → `user_<md512>@masked.local`
- phone → `+9100########`
- name → `Masked User <id8>`
- hashes → `sha256('masked:' \|\| id)` hex
- IP / UA → `0.0.0.0` / `masked`

Not covered here: payment JSON, transcripts, audio URLs (Tier 2/3).

## How it works

1. Migration [`20260825093000_tier1_pii_masking.sql`](../supabase/migrations/20260825093000_tier1_pii_masking.sql) installs helpers, `mask_tier1_pii_backfill()`, and `BEFORE INSERT OR UPDATE` triggers.
2. Triggers only rewrite rows when `pii_masking_config.enabled = true`.
3. After a refresh you **enable + backfill**; triggers stay on so later inserts/updates of Tier 1 fields are masked too.

## Staging refresh (dump → staging)

```bash
cd backend
export DATABASE_URL='postgresql://…staging…'   # never production
export SUPABASE_URL='https://…staging….supabase.co'
export SUPABASE_SECRET_KEY='…staging service role…'

./scripts/refresh_nonprod_db.sh /path/to/dump.dump
# or .sql / .sql.gz
```

This restores the dump, then runs:

```bash
python -m scripts.anonymize_tier1_pii \
  --enable --backfill --verify --i-understand-nonprod
```

## Local import

`reset` only re-applies migrations (no real PII). When you load a real dump:

```bash
cd backend
./scripts/local_supabase.sh import-dump /path/to/dump.dump
```

That restores into local Postgres (`54322`), enables masking, backfills, and verifies.

## Manual runner

```bash
cd backend
python -m scripts.anonymize_tier1_pii --enable --backfill --verify --i-understand-nonprod
python -m scripts.anonymize_tier1_pii --verify --i-understand-nonprod
python -m scripts.anonymize_tier1_pii --disable --i-understand-nonprod   # special tests only
```

### Guards

- Requires `--i-understand-nonprod`.
- Refuses project ref `nkwtxkhtsclyakympbno` (and any in `PII_MASK_PROD_PROJECT_REFS`) unless `PII_MASK_ALLOW_PROD=1` (ops escape hatch — avoid).
- Local is allowed when `SUPABASE_LOCAL=true` or host is `127.0.0.1` / `localhost`.

## Disable for a special test

```bash
python -m scripts.anonymize_tier1_pii --disable --i-understand-nonprod
```

Or SQL:

```sql
UPDATE public.pii_masking_config SET enabled = false, updated_at = now() WHERE id = 1;
```

Re-enable + backfill before sharing the DB again.

## Verify SQL

```sql
SELECT enabled FROM public.pii_masking_config WHERE id = 1;
SELECT public.pii_masking_is_enabled();

SELECT count(*) FROM public.users
WHERE email IS NOT NULL AND email !~ '@masked\.local$';
```
