# Deploying the ATLAS Prism API

The backend (`services/api/`) is published as a container on **Fly.io**. The
frontend is separate: `apps/web/` runs on Cloudflare Workers at
<https://atlasprism.aatech.ng> (`apps/web/wrangler.jsonc`).

Why these two live apart: the frontend is a Next.js app the Workers adapter
serves at the edge; the API is a long-lived Python process that executes
evaluation runs in-process and talks to PostgreSQL. A Worker cannot host the
second one.

## What is in the repository

| File | Purpose |
|---|---|
| `services/api/Dockerfile` | Production image. **Build context is the repository root.** |
| `services/api/docker-entrypoint.sh` | Release sequence: migrate → seed → serve. |
| `fly.toml` | Fly app config: region, non-secret env, health check, machine size. |
| `.dockerignore` | Keeps the frontend tree, both virtualenvs and every `.env` out of the build context. |

### Why the build context is the repository root

`app/evaluation/seed.py` locates the Guard and Shield baselines by walking up
from its own file (`parents[3].parent / "datasets"`). The image therefore
mirrors the repository layout — `/srv/services/api` and `/srv/datasets` — so
seeding finds the datasets. Building with `services/api/` as the context
cannot work: `datasets/` is outside it.

```bash
# correct
docker build -f services/api/Dockerfile -t atlas-prism-api .
```

## Release sequence

`docker-entrypoint.sh` runs on every boot, and every step fails loudly:

1. **`alembic upgrade head`** — the app never creates schema at startup
   (`docs/setup.md`). Idempotent.
2. **`python -m app.evaluation.seed`** — creates the admin user and the
   baseline suites. Idempotent: it skips what exists. Controlled by
   `PRISM_SEED_ON_START` (default `1`). With seeding on and `ADMIN_PASSWORD`
   empty, the seed exits non-zero and **the deploy fails** — that is the
   intended signal, not a bug.
3. **`uvicorn --workers 1`** — one worker, deliberately. A run executes in
   this process under an asyncio semaphore, and startup recovery marks
   interrupted runs failed; a second worker would duplicate that recovery and
   double the concurrency bound a run was created with.

## Secrets

Set through `fly secrets set`, never in `fly.toml` and never in a committed
file. Each one restarts the machine; none of them triggers a rebuild.

```bash
fly secrets set \
  DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST-pooler.REGION.aws.neon.tech/neondb?sslmode=require' \
  JWT_SECRET='<python -c "import secrets; print(secrets.token_urlsafe(48))">' \
  ADMIN_EMAIL='admin@example.com' \
  ADMIN_PASSWORD='<a real password, not the local one>'
```

- **`DATABASE_URL`** must use the `postgresql+psycopg://` scheme (SQLAlchemy
  needs the driver named) and keep `sslmode=require`. Use Neon's **pooled**
  host.
- **`JWT_SECRET`** must differ from the local development value. The JWT is a
  bearer token and Fly terminates TLS in front of the app.

### N-ATLAS gateway secrets

These change every time the Colab tunnel restarts — see
`services/inference/colab_launch.md`:

```bash
fly secrets set \
  NATLAS_BASE_URL='https://<tunnel-host>' \
  NATLAS_API_KEY='<key printed by the notebook>' \
  NATLAS_ALLOWED_HOSTS='<tunnel-host>'
```

`NATLAS_ALLOWED_HOSTS` is the SSRF allowlist. If the host is missing from it,
Prism refuses to call the endpoint — **that is the guard working**. Leaving
`NATLAS_API_KEY` empty is also a supported state: the API then reports
connections as blocked rather than faking success.

## Deploy

```bash
# From the repository root. --remote-only builds on Fly's builder, so a local
# Docker daemon is not required.
fly deploy --remote-only
```

Non-interactive (CI, or an agent session that cannot drive a browser login):

```bash
export FLY_API_TOKEN='<token from: fly tokens create deploy>'
fly deploy --remote-only
```

### Always scale back to one machine after a deploy

```bash
fly scale count 1 --app atlas-prism-api
fly machines list --app atlas-prism-api     # confirm exactly one
```

`fly deploy` adds a second machine for high availability by default. This app
cannot run two: `app/main.py`'s lifespan calls `recover_interrupted_runs()` at
startup, which marks every non-terminal run failed — so a second machine
booting while the first is executing a run would mark that live run failed.
Two machines also race on the migration and the seed. This bit the first
deploy (2026-10-11) and was corrected by scaling to 1.

### Live deployment, as of 2026-10-11

| | |
|---|---|
| URL | <https://atlas-prism-api.fly.dev> |
| App / org | `atlas-prism-api` / `personal` ("Azi Ai") |
| Region | `iad`, one `shared-cpu-1x` 512MB machine |
| Database | Neon pooled, `us-east-2` |
| Frontend origin allowed | `https://atlasprism.aatech.ng` (verified by preflight) |

**The database was already migrated and seeded** before this deploy — the
release log showed `admin: exists` and alembic reported no upgrade step. Since
seeding is idempotent, a newly generated `ADMIN_PASSWORD` is **not** applied to
an existing admin row; the login password remains whatever seeded it first.

## After the API is live

Two follow-ups, in this order:

1. **Confirm the origin is allowed.** `CORS_ALLOW_ORIGINS` in `fly.toml`
   already lists `https://atlasprism.aatech.ng`. If the frontend ever moves,
   update it there and redeploy — the browser blocks a missing origin before
   the request reaches a route.
2. **Rebuild the frontend against the live API.** `NEXT_PUBLIC_API_BASE_URL`
   is inlined into the browser bundle **at build time**; redeploying the
   existing Worker build changes nothing.

   ```bash
   cd apps/web
   # set NEXT_PUBLIC_API_BASE_URL=https://<app>.fly.dev/api/v1 in the build env
   npm run cf:deploy
   ```

   An HTTPS page cannot call `http://localhost` — the browser blocks it as
   mixed content, which is why the live site currently reaches only its empty
   states.

## Verification that actually counts

`GET /health` proves the API process is up and nothing more; it says so in its
own response. The integration claim is only this:

```bash
curl -X POST https://<app>.fly.dev/api/v1/connections/<id>/verify \
     -H "Authorization: Bearer <prism-token>"
```

Until that returns `"verified": true`, Prism-to-N-ATLAS integration is not
complete, however well the model runs inside Colab.

## Cost

One always-on `shared-cpu-1x` 512MB machine, from Fly's published pricing
(checked 2026-10-11): **$3.69/month**, plus outbound bandwidth at $0.02/GB in
North America. Stopped machines bill only rootfs storage ($0.15/GB/month).

`auto_stop_machines` is **off** on purpose. An evaluation run works with no
inbound traffic for minutes at a time; a scale-to-zero machine would be
suspended mid-run and the next boot would mark that run failed.
