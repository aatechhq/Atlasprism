# ATLAS Prism

**AI assurance for N-ATLAS integrations.** Connect a real
[N-ATLAS](https://huggingface.co/NCAIR1/N-ATLaS) deployment, run bounded
reliability and security tests against it, inspect exactly why each case passed
or failed, and export reproducible evidence.

Built by AA Technologies for the National AI Innovation Challenge (NAIC),
problem statement **PS1 — Developer Infrastructure**.

One evaluation pipeline, three views:

| Engine | What it does |
|---|---|
| **Guard** | Reliability and quality testing — deterministic scorers with explicit oracles |
| **Shield** | Authorized AI security testing — bounded prompt-injection and seeded-secret cases |
| **Pulse** | Evaluation-time observability — latency, errors and run history, all derived from persisted traces |

## Try it

| | |
|---|---|
| **Application** | <https://atlasprism.aatech.ng> |
| **API** | <https://atlas-prism-api.fly.dev> ([OpenAPI](https://atlas-prism-api.fly.dev/docs)) |

Sign up on the site, then: create a project → connect your N-ATLAS endpoint →
import or create a test suite → run it → inspect the failures → export the
report. Each account only ever sees its own projects.

## Status: the integration is live and verified

**`POST /api/v1/connections/{id}/verify` returned `verified: true`** on
2026-10-11T23:25:27Z — a genuine authenticated generation, **925 ms**, upstream
HTTP 200, model `NCAIR1/N-ATLaS`. It was driven by the deployed API, not a
developer laptop.

A full run through the same deployed stack, run
`82d37773-1ef0-49ce-b03d-958459acae81`:

| | |
|---|---|
| Cases | 20 (10 Guard + 10 Shield), concurrency 1 |
| Outcome | **16 passed, 4 failed, 0 errors**, pass rate 0.80 |
| Duration | 56 s |
| Pulse | 22/22 successful inferences · 0 transport, auth or blocked · mean 2329 ms, median 1947 ms, p95 5586 ms |
| Exports | JSON and CSV, both HTTP 200 |

Evidence files, with timestamps, are committed under
[`services/api/docs/integration-evidence/`](services/api/docs/integration-evidence/).
No credential appears in any of them.

**Measurement integrity** — two properties that make these numbers trustworthy:

- **Results are tied to a run, not asserted as a model property.** Generation
  is sampled (`temperature` defaults to 0.7), so the same 20 cases gave 0.75,
  0.75 and 0.80 across three runs. Prism therefore reports per-run results with
  an immutable configuration snapshot, and provides `repeat_count` for
  measuring across repeats — which is how a reproducible benchmark has to
  work.
- **Every verdict traces to an explicit, pre-declared oracle.** Prism measures
  behaviour against deterministic checks rather than asking another model for an
  opinion, and each scorer documents what it does and does not establish. See
  [docs/evaluation-methodology.md](docs/evaluation-methodology.md).

All metrics derive from persisted inference traces. No simulated inference is
ever presented as real.

## Deployed architecture

```
browser (Cloudflare Worker, Next.js)        https://atlasprism.aatech.ng
   │  signs in via Neon Auth, sends the resulting JWT on every request
   ▼
Prism API (FastAPI on Fly.io, region iad)   https://atlas-prism-api.fly.dev
   ├── projects, suites, runs, traces  ──►  Neon PostgreSQL (us-east-2)
   └── inference  ──►  N-ATLAS on Lightning AI (Tesla T4, 4-bit NF4)
                          │
                   response returned to the API, which scores it,
                   persists the trace, and answers the browser
```

The browser never talks to the model and never holds the inference key — only
the API does. The evaluation platform and the model under test are deployed
independently, which is what lets Prism credibly *assess* N-ATLAS rather than
being part of it.

```
atlas-prism/
├── apps/web/              # Next.js frontend, deployed as a Cloudflare Worker
├── services/api/          # Prism backend: FastAPI + SQLAlchemy + PostgreSQL
├── services/inference/    # Standalone GPU service that serves N-ATLAS over HTTP
├── datasets/              # Guard and Shield baseline suites (JSON)
└── docs/                  # Architecture, setup, usage, methodology, API contract
```

`services/inference/` is deliberately separate: PyTorch, BitsAndBytes, Hugging
Face auth and model loading live there, on GPU hardware. The Prism backend
speaks plain HTTP to it and has **no ML dependencies at all**.

## N-ATLAS integration

Prism speaks to N-ATLAS over the documented gateway contract, through a single
connector (`services/api/app/connectors/natlas.py`). There is **one** adapter
and no fallback to any other provider.

| | |
|---|---|
| Endpoints used | `POST /v1/chat/completions` for inference, and `GET /health` for a diagnostic reachability probe only |
| Authentication | `Authorization: Bearer $NATLAS_API_KEY`, loaded server-side only |
| Default model id | `NCAIR1/N-ATLaS` |
| Timeout | `NATLAS_TIMEOUT_MS` (120000 against GPU hosting) |
| Host allowlist | `NATLAS_ALLOWED_HOSTS` — an SSRF guard; a host not listed is refused |

The connector calls **only** those two paths: `/v1/chat/completions` is the
inference call, and `/health` backs
`GET /api/v1/connections/{id}/gateway-health`, a reachability probe whose own
docstring states it is *"explicitly NOT integration evidence"*. The gateway's
`/v1/models` route is not consulted by Prism.

The connector normalises prompt, response, model id, timing and usage into one
shape, and classifies failures explicitly: `401`, `429`, timeout, network and
upstream error are distinct outcomes. **An error is never scored as a quality
failure or as a passed security defence** — it is recorded as `error` and
excluded from the pass rate.

What establishes the integration:

```
POST /api/v1/connections/{id}/verify   ->   "verified": true
```

That endpoint performs a **real authenticated generation**. A successful
`/health` check does not count and the endpoint says so in its own response
body. Credentials are never returned by any API route, and never appear in a
report, trace or export — only `configured (****last4)`.

If no key is configured, Prism reports connections as `blocked` rather than
simulating success. Nothing in this repository substitutes another model for
N-ATLAS.

## Run it locally

Requires Python 3.11+, Docker, and [uv](https://docs.astral.sh/uv/).

```bash
# 1. PostgreSQL
docker run -d --name atlas-prism-db \
  -e POSTGRES_USER=prism -e POSTGRES_PASSWORD=prism -e POSTGRES_DB=atlas_prism \
  -p 55433:5432 postgres:16-alpine

# 2. Backend
cd services/api
uv venv .venv && uv pip install --python .venv -e ".[dev]"
cp .env.example .env           # then edit it - see below
.venv/bin/alembic upgrade head          # Windows: .venv/Scripts/alembic.exe
.venv/bin/python -m app.evaluation.seed # admin user + both baseline suites
.venv/bin/python -m uvicorn app.main:app --port 8000
```

Open <http://localhost:8000/docs> for the live OpenAPI schema.

Minimum `.env` edits: set `JWT_SECRET` and `ADMIN_PASSWORD` to real values, and
keep `AUTH_MODE=local` so the password login works for local development. Set
`NATLAS_API_KEY` only when you actually have a gateway key — leaving it empty is
correct, and makes Prism report connections as `blocked` rather than faking
success.

**Authentication differs between local and deployed.** Locally, `AUTH_MODE=local`
uses the seeded admin with `POST /api/v1/auth/login`. The deployed API runs
`AUTH_MODE=neon` and validates Neon Auth tokens against its JWKS, which is what
the website uses. Scripts written against password login cannot authenticate to
the deployed API.

### Tests

```bash
cd services/api && .venv/bin/python -m pytest -q
cd services/inference && .venv/bin/python -m pytest -q
```

The backend tests create and drop their own PostgreSQL databases, so Docker must
be running. No test contacts a real model — the model layer is injected, so the
HTTP surface, auth and error handling are covered on a laptop.

### Serve N-ATLAS yourself

For a persistent deployment on GPU hosting, follow
[`services/inference/lightning_launch.md`](services/inference/lightning_launch.md)
— that is what the live endpoint uses. For a quick throwaway run from a
notebook, [`services/inference/colab_launch.md`](services/inference/colab_launch.md)
still works, but a Colab tunnel hostname dies with the runtime.

Prism takes the endpoint from `NATLAS_BASE_URL` and the key from
`NATLAS_API_KEY`, and refuses to send inference to any host not listed in
`NATLAS_ALLOWED_HOSTS` — an SSRF guard. A rejected host is the guard working,
not a bug.

## Documentation

| Document | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Components, data flow, execution model and its limits |
| [docs/setup.md](docs/setup.md) | Install, migrate, seed, configure |
| [docs/usage.md](docs/usage.md) | End-to-end walkthrough with real requests |
| [docs/deployment-api.md](docs/deployment-api.md) | How the API is deployed, and its secrets |
| [services/inference/lightning_launch.md](services/inference/lightning_launch.md) | Serving N-ATLAS persistently on GPU hosting |
| [docs/evaluation-methodology.md](docs/evaluation-methodology.md) | Guard, Shield and Pulse — every scorer, what it proves and what it does not |
| [docs/testing.md](docs/testing.md) | How to run the tests, what they cover and what they cannot |
| [docs/reporting.md](docs/reporting.md) | Report contents, export formats, redaction and limitations |
| [docs/beta-testing.md](docs/beta-testing.md) | External developer assessment and independent verification |
| [docs/api-contract.md](docs/api-contract.md) | The REST contract the frontend builds against |
| [docs/implementation-status.md](docs/implementation-status.md) | Implemented / tested / live-verified / blocked |

## Licence

[MIT](LICENSE) — chosen by the project owner on 2026-10-11. Copyright holder:
AA Technologies.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
