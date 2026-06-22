#!/usr/bin/env sh
# Generate JWT secrets for Railway production (run locally, paste into Railway Variables).
set -eu
echo "JWT_SECRET=$(openssl rand -hex 32)"
echo "JWT_REFRESH_SECRET=$(openssl rand -hex 32)"
