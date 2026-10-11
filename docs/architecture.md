# Architecture

## Components

```
                   ┌──────────────────────┐
                   │  apps/web (UI)       │
                   │  Next.js frontend    │
                   └──────────┬───────────┘
                              │ HTTPS, JSON, Bearer JWT
                              ▼
┌──────────────────────────────────────────────────────┐
│  services/api - ATLAS Prism backend (FastAPI)        │
│                                                      │
│  api/v1/      routers + auth & ownership deps        │
│  evaluation/  run orchestration, scorers             │
│  engines/     guard · shield · pulse                 │
│  connectors/  ModelConnector → NatlasConnector       │
│  reporting/   JSON + CSV evidence exports            │
│  models/      SQLAlchemy entities                    │
└───────┬──────────────────────────────┬───────────────┘
        │ SQLAlchemy                   │ HTTPS + Bearer
        ▼                              ▼
┌──────────────────┐      ┌─────────────────────────────────┐
│   PostgreSQL     │      │  services/inference (GPU host)  │
│   10 tables      │      │  FastAPI + Transformers         │
│   Alembic        │      │  NCAIR1/N-ATLaS @ 4-bit NF4     │
└──────────────────┘      └─────────────────────────────────┘
```

**Why the inference service is separate.** The Prism backend has no ML
dependencies — no torch, no transformers, no Hugging Face client. Model
loading, quantization and HF authentication live in `services/inference`, which
runs on GPU hardware (Colab T4 initially, dedicated GPU hosting for the judging
period). Prism reaches it over HTTP at `NATLAS_BASE_URL`. Moving the model
between hosts is a configuration change, not a code change, and nothing about
Prism's correctness depends on where the model runs.

## Data flow of one evaluation run

1. `POST /api/v1/runs` validates ownership of the project, connection and
   suites.
2. **The run and every case are persisted first**, inside one transaction, with
   `status = queued` and an immutable `case_snapshot` per case. Then the run id
   is returned (HTTP 202) — before any inference happens.
3. A background task executes the cases with a bounded `asyncio.Semaphore`
   (`max_concurrency`, capped by `RUN_MAX_CONCURRENCY`).
4. Each case builds its messages from its snapshot, calls the connector once
   per `repeat_count`, and **writes an `inference_traces` row for every
   attempt** — successful or not.
5. Only an `ok` outcome is handed to a scorer. Anything else means the case is
   `error` with `passed = NULL`.
6. A Shield case that fails also writes a `security_findings` row naming the
   exact rule.
7. The run's terminal status is computed from its cases:
   `completed` (no errors), `partially_completed` (some scored, some errored),
   or `failed` (nothing scorable).

## Execution model and its limits

Execution uses a **FastAPI background task in the API process**. This is a
deliberate choice for a V0.1 with a hard deadline, and its limits are stated
rather than hidden:

- If the process restarts mid-run, that run has no worker. `recover_interrupted_runs()`
  runs at startup and marks such runs `failed`, and their unfinished cases
  `error` with `error_kind = "interrupted"`.
- Progress is observed by **polling** `GET /runs/{id}`. There is no websocket.
- **This is not a durable queue** and is not described as one. Celery, RQ or
  Arq would be the upgrade path; none is warranted at this scale.

## Trust and safety boundaries

| Boundary | Control |
|---|---|
| Who can read a project | JWT → `owner_id` check on every resource; a foreign id returns **404**, not 403, so the API does not confirm other tenants' ids exist |
| Where inference may be sent | `NATLAS_ALLOWED_HOSTS` allowlist, enforced both when a connection is stored and before every call (SSRF guard) |
| Credential handling | Key lives only in the server environment; `model_connections.secret_ref` records *where* it lives, never the value. Responses show `configured (****last4)` |
| Secrets in evidence | Exports mask every literal a case declared in `seeded_secrets`, including occurrences in prompts and model responses |
| Runaway cost | `RUN_MAX_CASES`, `RUN_MAX_CONCURRENCY`, `RUN_MAX_REPEATS`, and a per-request timeout |
| Fixture leakage | `FakeConnector` raises unless `ATLAS_PRISM_ALLOW_FAKE_CONNECTOR=1`; a test asserts no production module imports it |

## Schema

Ten tables. See `app/models/entities.py` for the authoritative definitions.

| Table | Purpose |
|---|---|
| `users` | Identity (single admin in V0.1) |
| `projects` | Ownership boundary for everything else |
| `model_connections` | Endpoint, model id, secret *reference*, verification state |
| `test_suites` / `test_cases` | Guard and Shield definitions, versioned |
| `test_runs` | One execution: status, counts, suite snapshot, scoring version |
| `run_cases` | Per-case result + **immutable snapshot** of the case as launched |
| `inference_traces` | One row per attempted call — the sole source of Pulse metrics |
| `security_findings` | A failed Shield case, tied to its rule and severity rationale |
| `report_exports` | Audit trail of generated evidence |

**Reproducibility** means the inputs, rules and recorded evidence are fixed:
case snapshot, suite version, scoring version, model and connection id,
timestamps, and the stored response. It does **not** mean the model will
generate identical text on a re-run — live inference is nondeterministic, and
every export says so.
