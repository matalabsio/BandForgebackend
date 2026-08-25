#!/usr/bin/env bash
# Restore a Postgres dump into a non-prod DATABASE_URL, then enable + backfill Tier 1 PII masking.
#
# Usage (from backend/):
#   DATABASE_URL='postgresql://…' ./scripts/refresh_nonprod_db.sh /path/to/dump.dump
#   DATABASE_URL='postgresql://…' ./scripts/refresh_nonprod_db.sh /path/to/dump.sql
#
# Env:
#   DATABASE_URL          Required — staging/local connection string (NOT production)
#   SUPABASE_URL          Used by anonymize_tier1_pii.py (staging/local API URL)
#   SUPABASE_SECRET_KEY   Service role key for staging/local
#   PII_MASK_PROD_PROJECT_REFS  Optional extra deny-list (comma-separated refs)
#
# Never point DATABASE_URL / SUPABASE_URL at production.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

red() { printf '\033[0;31m%s\033[0m\n' "$*"; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[1;33m%s\033[0m\n' "$*"; }

DUMP="${1:-}"
if [[ -z "$DUMP" ]]; then
  red "Usage: DATABASE_URL=… ./scripts/refresh_nonprod_db.sh <dump.dump|dump.sql>"
  exit 1
fi
if [[ ! -f "$DUMP" ]]; then
  red "Dump not found: $DUMP"
  exit 1
fi
if [[ -z "${DATABASE_URL:-}" ]]; then
  red "DATABASE_URL is required (staging/local Postgres URI)."
  exit 1
fi

# Soft guard: refuse obvious prod hostnames in DATABASE_URL
if [[ "$DATABASE_URL" == *"nkwtxkhtsclyakympbno"* ]]; then
  red "Refusing DATABASE_URL that looks like production (nkwtxkhtsclyakympbno)."
  red "Use a staging or local connection string."
  exit 1
fi

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    red "Missing required command: $1"
    exit 1
  fi
}

need psql
need python3

PYTHON="python3"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

yellow "Restoring $DUMP into DATABASE_URL …"

case "$DUMP" in
  *.sql|*.sql.gz)
    if [[ "$DUMP" == *.gz ]]; then
      need gzip
      gzip -dc "$DUMP" | psql "$DATABASE_URL" -v ON_ERROR_STOP=1
    else
      psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$DUMP"
    fi
    ;;
  *)
    need pg_restore
    # --clean --if-exists so refresh replaces objects; ignore role errors common on Supabase
    pg_restore --no-owner --no-acl --clean --if-exists -d "$DATABASE_URL" "$DUMP" \
      || yellow "pg_restore exited non-zero (often role/ACL noise); continuing to anonymize if DB is usable"
    ;;
esac

green "Restore step finished."
yellow "Enabling Tier 1 PII masking + backfill + verify …"

"$PYTHON" -m scripts.anonymize_tier1_pii \
  --enable \
  --backfill \
  --verify \
  --i-understand-nonprod

green "Non-prod refresh complete. Masking triggers remain enabled for new writes."
