# ATLAS Prism API -- production image.
#
# BUILD CONTEXT IS THE REPOSITORY ROOT, not services/api:
#   docker build -f services/api/Dockerfile -t atlas-prism-api .
#
# The repository layout is mirrored inside the image on purpose.
# app/evaluation/seed.py locates datasets/ by walking up from its own file
# (parents[3].parent / "datasets"), so services/api/ and datasets/ must keep
# the same relative positions they have in the repo or seeding cannot find
# the Guard and Shield baselines.
FROM python:3.12-slim

# No .pyc files, unbuffered logs so the platform's log tail is live.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/services/api

# psycopg is installed as psycopg[binary] (wheels include libpq), so no
# build-essential or libpq-dev is needed here. curl is for the healthcheck.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# The whole service is copied before install because the wheel build needs the
# app package present. One layer, no dependency-cache trick that could serve a
# stale set of dependencies -- correctness over build speed.
COPY services/api/ /srv/services/api/
RUN pip install --no-cache-dir .

# Seeded Guard/Shield baselines, read at seed time from the repo root.
COPY datasets/ /srv/datasets/

COPY services/api/docker-entrypoint.sh /usr/local/bin/entrypoint
RUN chmod +x /usr/local/bin/entrypoint

# Overridden by the platform ($PORT); 8000 is only the local default.
ENV PORT=8000
EXPOSE 8000

# Liveness of the API process only. It deliberately says nothing about
# N-ATLAS -- that is proven by POST /api/v1/connections/{id}/verify.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" > /dev/null || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint"]
