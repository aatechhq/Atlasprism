#!/bin/sh
# Release sequence for the ATLAS Prism API container.
#
#   1. migrate  -- the app never creates schema at startup (docs/setup.md)
#   2. seed     -- idempotent: creates the admin and baseline suites once
#   3. serve    -- uvicorn, one worker
#
# Every step fails loudly. A deploy that cannot migrate or cannot seed must
# not come up serving an empty database behind a 200 /health.
set -eu

echo "[release] alembic upgrade head"
alembic upgrade head

# Seeding is on by default because a fresh database has no admin user and
# login would be impossible. Set PRISM_SEED_ON_START=0 once the database is
# populated. With it on and ADMIN_PASSWORD empty, app.evaluation.seed exits
# non-zero and this deploy fails -- that is the intended signal, not a bug.
if [ "${PRISM_SEED_ON_START:-1}" = "1" ]; then
  echo "[release] python -m app.evaluation.seed"
  python -m app.evaluation.seed
else
  echo "[release] seeding skipped (PRISM_SEED_ON_START=0)"
fi

# ONE worker, deliberately. A run executes in this process under an asyncio
# semaphore (app/evaluation/runner.py) and startup recovery marks interrupted
# runs failed; a second worker would duplicate that recovery and double the
# concurrency bound the run was created with.
echo "[release] uvicorn on 0.0.0.0:${PORT:-8000}"
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips '*'
