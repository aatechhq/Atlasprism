# Setup

## Requirements

- Python 3.11+ (3.12 recommended)
- Docker (for PostgreSQL)
- [uv](https://docs.astral.sh/uv/) — or use `python -m venv` and `pip install -e .`
- A GPU host, only if you are serving the model yourself (see the bottom)

## 1. PostgreSQL

```bash
docker run -d --name atlas-prism-db \
  -e POSTGRES_USER=prism -e POSTGRES_PASSWORD=prism -e POSTGRES_DB=atlas_prism \
  -p 55433:5432 postgres:16-alpine
```

Port **55433** is used rather than 5432 to avoid colliding with an existing
local PostgreSQL. Match whatever you choose in `DATABASE_URL`.

## 2. Install

```bash
cd services/api
uv venv .venv
uv pip install --python .venv -e ".[dev]"
```

On Windows the interpreter is `.venv/Scripts/python.exe`; on macOS/Linux
`.venv/bin/python`.

## 3. Configure

```bash
cp .env.example .env
```

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | `postgresql+psycopg://prism:prism@localhost:55433/atlas_prism` |
| `JWT_SECRET` | yes | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `JWT_EXPIRE_MINUTES` | no | Default 720 |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | yes | Seeded admin. Change before any deployment. |
| `NATLAS_BASE_URL` | yes | Inference endpoint, no trailing slash |
| `NATLAS_API_KEY` | no | **Leave empty if you do not have one.** Empty ⇒ connections report `blocked` instead of faking success. |
| `NATLAS_MODEL_ID` | no | Default `NCAIR1/N-ATLaS` |
| `NATLAS_TIMEOUT_MS` | no | Default 60000 |
| `NATLAS_ALLOWED_HOSTS` | yes | Comma-separated SSRF allowlist. A host missing here is refused. |
| `AUTH_MODE` | no | `local` (default) or `neon` — see below |
| `NEON_AUTH_JWKS_URL` / `NEON_AUTH_ISSUER` / `NEON_AUTH_AUDIENCE` | only when `AUTH_MODE=neon` | See the warning below: the issuer is **not** the JWKS path |
| `CORS_ALLOW_ORIGINS` | no | Browser origins allowed to call the API. A deployed frontend **must** be listed or the browser blocks every request before it reaches a route. |
| `RUN_MAX_CONCURRENCY` / `RUN_MAX_CASES` / `RUN_MAX_REPEATS` | no | Cost guards: 2 / 200 / 5 |

### Authentication: two modes, not interchangeable

| `AUTH_MODE` | How a caller authenticates |
|---|---|
| `local` (default) | `POST /api/v1/auth/login` with the seeded `ADMIN_EMAIL` / `ADMIN_PASSWORD` returns an HS256 JWT signed with `JWT_SECRET`. Use this for local development and scripts. |
| `neon` | The caller presents a **Neon Auth** token, which the API verifies against `NEON_AUTH_JWKS_URL` (an `EdDSA`/`Ed25519` key). This is what the deployed API and the website use. |

**A script written against password login cannot authenticate to an API running
in `neon` mode** — `/auth/login` will still mint a token and every protected
route will then reject it. That is expected, not a bug.

> **⚠ `NEON_AUTH_ISSUER` must be the bare origin**, e.g.
> `https://<id>.neonauth.<region>.aws.neon.tech` — **not** the auth base URL
> with `/neondb/auth` appended. Neon puts the bare origin in the token's `iss`
> claim, PyJWT compares it exactly, and a mismatch makes every signed-in
> request fail with `401 "Invalid or expired token."` The **JWKS URL**, by
> contrast, *does* keep the `/neondb/auth/.well-known/jwks.json` path. This
> exact mismatch broke the live site on 2026-10-11; verify it by decoding a
> real token from `GET /api/auth/token` rather than assuming.

**Never commit `.env`.** It is gitignored; `.env.example` holds no real values.

## 4. Migrate

```bash
.venv/bin/alembic upgrade head
```

This builds all ten tables from empty. Verify:

```bash
docker exec atlas-prism-db psql -U prism -d atlas_prism -c "\dt"
```

## 5. Seed

```bash
.venv/bin/python -m app.evaluation.seed
```

Creates the admin user, a baseline project, and both suites from `datasets/`
(10 Guard + 10 Shield cases). Idempotent: re-running skips what exists and
reports what it did.

## 6. Run

```bash
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- OpenAPI UI: http://localhost:8000/docs
- `GET /health` — API liveness only. It deliberately says nothing about
  N-ATLAS; model integration is proven only by
  `POST /api/v1/connections/{id}/verify`.

## 7. Smoke test

```bash
# Log in
curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"<ADMIN_EMAIL>","password":"<ADMIN_PASSWORD>"}'

# With the token:
curl -s localhost:8000/api/v1/projects -H "Authorization: Bearer $TOKEN"
```

Then follow [usage.md](usage.md) for the full connect → test → export flow.

## Connecting a real N-ATLAS model

Prism does not host the model. Point it at a service that does:

1. Stand up `services/inference` on GPU hardware. For a persistent endpoint
   with a stable hostname — what the live deployment uses — follow
   [`../services/inference/lightning_launch.md`](../services/inference/lightning_launch.md).
   For a throwaway run from a notebook, see
   [`../services/inference/colab_launch.md`](../services/inference/colab_launch.md);
   note that a Colab tunnel hostname dies with the runtime, and both
   `NATLAS_BASE_URL` and `NATLAS_ALLOWED_HOSTS` must be updated each time it
   changes.
2. Set in `services/api/.env`:
   ```
   NATLAS_BASE_URL=https://<your-inference-host>
   NATLAS_API_KEY=<the service's INFERENCE_API_KEY>
   NATLAS_ALLOWED_HOSTS=<your-inference-host>
   ```
3. Restart the API, then verify through Prism:
   ```bash
   curl -X POST localhost:8000/api/v1/connections/<id>/verify \
        -H "Authorization: Bearer $TOKEN"
   ```
   `"verified": true` means Prism made a real authenticated generation call and
   recorded the latency, model id and a response excerpt. Anything else is
   reported honestly as `failed` or `blocked`.

If the endpoint host is not in `NATLAS_ALLOWED_HOSTS`, Prism refuses to call it.
That is the SSRF guard working, not a bug.

## Deployment notes

- Set every secret through the platform's secret manager, never a committed file.
- Run `alembic upgrade head` as a release step; the app does not create schema
  at startup.
- Serve behind TLS. The JWT is a bearer token.
- Tighten CORS in `app/main.py` — it currently allows `localhost:3000` for local
  frontend development.
- Interrupted runs are marked `failed` at startup, so a restart cannot leave a
  run stuck in `running` forever.
