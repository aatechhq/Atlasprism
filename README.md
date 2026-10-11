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

## Honest status

Read [`docs/implementation-status.md`](docs/implementation-status.md) before
judging what works. The short version:

- The backend, database, evaluation engine, 10 Guard + 10 Shield baseline
  cases, Pulse metrics and JSON/CSV exports are **implemented and tested**.
- **Live inference against the official N-ATLAS weights is NOT yet verified.**
  The connector is complete and the contract is proven end to end against a
  locally-hosted instance of our own inference service, but a real
  `NCAIR1/N-ATLaS` generation has not yet been recorded. Until it is, every
  connection reports `blocked` rather than a fabricated success.
- Nothing in this repository simulates inference and presents it as real.

## Architecture

```
atlas-prism/
├── apps/web/              # Frontend         - consumes the API below
├── services/api/          # Prism backend: FastAPI + PostgreSQL  <- this is the product
├── services/inference/    # Standalone GPU service that serves N-ATLAS over HTTP
├── datasets/              # Guard and Shield baseline suites (JSON)
└── docs/                  # Architecture, setup, usage, methodology, API contract
```

`services/inference/` is deliberately separate: PyTorch, BitsAndBytes, Hugging
Face auth and model loading live there, on GPU hardware. The Prism backend
speaks plain HTTP to it and has no ML dependencies at all.

## Quickstart

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

Open http://localhost:8000/docs for the live OpenAPI schema.

Minimum `.env` edits: set `JWT_SECRET` and `ADMIN_PASSWORD` to real values. Set
`NATLAS_API_KEY` only when you actually have a gateway key — leaving it empty
is correct and makes Prism report connections as `blocked`.

### Run the tests

```bash
cd services/api && .venv/bin/python -m pytest -q        # 97 tests
cd services/inference && .venv/bin/python -m pytest -q  # 17 tests
```

The backend tests create and drop their own PostgreSQL databases, so Docker
must be running. No test contacts a real model.

### Connect a real model

See [`docs/setup.md`](docs/setup.md) and
[`services/inference/colab_launch.md`](services/inference/colab_launch.md).
Prism takes the endpoint from `NATLAS_BASE_URL` and the key from
`NATLAS_API_KEY`, and refuses to send inference to any host not listed in
`NATLAS_ALLOWED_HOSTS`.

## Documentation

| Document | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Components, data flow, execution model and its limits |
| [docs/setup.md](docs/setup.md) | Install, migrate, seed, configure, deploy |
| [docs/usage.md](docs/usage.md) | End-to-end walkthrough with real requests |
| [docs/evaluation-methodology.md](docs/evaluation-methodology.md) | Every scorer, what it proves and what it does not |
| [docs/api-contract.md](docs/api-contract.md) | The REST contract the frontend builds against |
| [docs/implementation-status.md](docs/implementation-status.md) | Implemented / tested / live-verified / blocked |

## Licence

**Not yet chosen.** PS1 requires a public repository under a valid open-source
licence; selecting it is the project owner's decision and it has not been made
yet. No `LICENSE` file is included rather than one being guessed at. See
`docs/implementation-status.md`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
