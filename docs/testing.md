# Testing

How to run ATLAS Prism's automated tests, what they cover, and — just as
importantly — what they do **not** cover.

## Running the tests

### Backend (`services/api`)

```bash
cd services/api
uv venv .venv && uv pip install --python .venv -e ".[dev]"
.venv/bin/python -m pytest -q          # Windows: .venv/Scripts/python.exe
```

**Prerequisite: a reachable PostgreSQL that the test user may create and drop
databases on.** The suite creates and destroys `atlas_prism_test` and
`atlas_prism_migration_test`. If `DATABASE_URL` points at a managed database
whose role lacks `CREATEDB` — a pooled Neon connection, for example — the
tests error out during setup rather than failing assertions. Run them against
the local Docker PostgreSQL from [setup.md](setup.md), not against a
production database.

### Inference service (`services/inference`)

```bash
cd services/inference
uv venv .venv && uv pip install --python .venv -e ".[dev]"
.venv/bin/python -m pytest -q
```

These run on a laptop with no GPU and download no model weights: the model
layer is injected, so the HTTP surface, authentication and error handling are
exercised against a stub engine. One test is skipped unless `torch` is
installed, because `torch` is a GPU-host dependency deliberately kept off
development machines.

### Frontend (`apps/web`)

```bash
cd apps/web
npm install
npm run typecheck      # tsc --noEmit
npm run build          # next build
```

**There is no browser or component test suite.** Type-checking and a
successful production build are the only automated gates. Frontend behaviour
has been verified by driving the deployed site, not by automated tests.

## What the tests cover

| Area | Covered by |
|---|---|
| Configuration and structured error shapes | backend unit tests |
| Schema and migrations | a test that applies `alembic upgrade head` to a genuinely blank database and asserts the resulting tables and foreign keys |
| Authentication, both modes | password/JWT path, and Neon Auth token validation |
| Project scoping | another tenant's ids return 404, not 403 |
| Guard scorers | each evaluator type against passing and failing inputs |
| Shield detectors | each detector, including a seeded-secret case that must not leak into output |
| Run lifecycle | queued → running → terminal states, bounded concurrency, repeat counts, interrupted-run recovery |
| Errors vs failures | a service, network or parse problem is recorded `error` and never counted as a passed defence or a quality failure |
| Pulse metrics | computed from persisted traces, including the "not enough attempts" path |
| Exports | JSON and CSV, including redaction of seeded Shield literals |
| SSRF guard | a non-allowlisted endpoint host is refused |

The current executed counts are recorded in
[implementation-status.md](implementation-status.md) under *Test results
(actually executed)*, with the date they were run. That document is the
authority on what has actually been executed; this one explains how to
reproduce it.

## What the tests do not cover

- **No test contacts a real model.** The only mocked component anywhere is the
  model connector. `FakeConnector` raises unless
  `ATLAS_PRISM_ALLOW_FAKE_CONNECTOR=1` is set, and a test asserts that no
  production module imports it. Real-model behaviour is therefore evidenced by
  live verification, not by the test suite — see
  [implementation-status.md](implementation-status.md) and the artifacts in
  [`../services/api/docs/integration-evidence/`](../services/api/docs/integration-evidence/).
- **A passing suite says nothing about N-ATLAS.** It says Prism's pipeline is
  correct. Those are different claims and this project keeps them separate.
- **No load or soak testing.** Execution is a bounded in-process background
  task, not a durable queue; see *Execution model and its limits* in
  [architecture.md](architecture.md).
- **No browser automation.** See the frontend note above.

## Live verification

Automated tests cannot prove the integration, because they deliberately never
call the model. The claim that counts is:

```
POST /api/v1/connections/{id}/verify   ->   "verified": true
```

A green `/health` is not evidence of inference, and the endpoint says so in its
own response body. The procedure for establishing and recording live
verification is in [usage.md](usage.md), and
`services/api/scripts/verify_live.py` automates it end to end, writing a
timestamped evidence file.

> **Note on repeatability of results, not of tests.** Generation is sampled
> (`temperature` defaults to 0.7), so re-running the *same* suite against the
> *same* model can give a different pass rate — observed 0.75, 0.75 and 0.80
> across three runs of the 20-case baseline. The tests are deterministic; model
> behaviour is not. Cite a run id, or raise `repeat_count`, rather than
> treating one pass rate as a property of the model.
