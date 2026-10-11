# ATLAS Prism frontend handoff

## Runtime

- App: `apps/web` (Next.js App Router, strict TypeScript)
- API configuration: `NEXT_PUBLIC_API_BASE_URL`, default `http://localhost:8000/api/v1`
- Authentication: bearer token held in browser session storage and cleared on sign-out or 401. N-ATLAS credentials never enter the frontend.

## Implemented routes

`/login`, `/dashboard`, `/projects`, `/suites`, `/runs`, `/runs/[runId]`, `/results`, `/results/[runId]`, `/pulse`, `/reports`.

## Confirmed API surface consumed

- `POST /auth/login`
- `GET/POST /projects`
- `GET/POST /connections`; `POST /connections/{id}/verify`
- `GET/POST /suites`; `GET /suites/{id}`
- `GET/POST /runs`; `GET /runs/{id}`; `GET /runs/{id}/results`
- `GET /metrics/summary`; `GET /traces`
- `GET /reports/{runId}/export?format=json|csv`

The frontend mirrors DTOs currently present in `services/api/app/schemas/api.py`. `docs/api-contract.md` was not present when integration began; backend schema remains authoritative.

## Truthful status

| Area | Built | API-connected | Browser-verified | Live N-ATLAS verified |
|---|---:|---:|---:|---:|
| Auth and app shell | yes | yes | verified against local FastAPI | n/a |
| Projects and connection verification | yes | yes | verified against local FastAPI | blocked: official model credential/endpoint unavailable to Prism |
| Suites and run launcher | yes | yes | verified against seeded projects, suites and historical runs | blocked for a new official-model run |
| Results, Pulse and exports | yes | yes | verified with persisted cases, 108 traces and JSON export | blocked for official-model evidence |

No production route has a fixture fallback. Missing or failed API data produces an explicit loading, empty, disabled, or error state.

Browser-to-API verification used the local seeded admin and persisted backend
records. It confirmed structured API errors, authenticated navigation, nested
Pulse metrics, result evidence, scoring-version display and authenticated JSON
download. Historical successful records came from the backend's documented
stub-engine contract run and are not evidence of official N-ATLAS behaviour.
