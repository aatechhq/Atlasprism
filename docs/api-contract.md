# API contract

**Audience: the frontend (`apps/web`, owned separately).** This is the agreed
interface. The authoritative, always-current schema is the OpenAPI document the
running backend generates:

- http://localhost:8000/openapi.json
- http://localhost:8000/docs (interactive)

Generate a typed client from that rather than hand-writing types.

**If a route or shape changes, this document changes in the same commit** and
the frontend owner is told before the change lands. Do not build against a
mock API of your own: every route below is implemented and returns real data.

Base path: `/api/v1`. Transport: JSON over HTTP.

## Auth

`POST /api/v1/auth/login` → `{"access_token", "token_type":"bearer", "expires_in_minutes"}`

Send `Authorization: Bearer <token>` on every other route. `GET /api/v1/auth/me`
returns the current user.

- `401` — missing, malformed or expired token. Identical message for an unknown
  email and a wrong password (no account enumeration).
- `404` — a resource that exists but belongs to someone else. **Treat 404 as
  "not available to you", not necessarily "does not exist".**

## Error shape

Every error has the same envelope:

```json
{"detail": {"code": "bad_request", "message": "Human-readable explanation.", "…": "extra context"}}
```

Codes: `unauthorized`, `forbidden`, `not_found`, `bad_request`,
`connection_blocked`, `error`. Render `message` directly — it is written to be
shown. Some errors add context keys (e.g. `valid_evaluators`, `allowed_hosts`,
`missing_suite_ids`, `pattern`). **No error body ever contains a credential.**

### Reading an error correctly

`detail` is **not a string**. It is an object for every error this API raises,
and an **array** for FastAPI's own 422 request-validation errors:

```json
// 400/401/403/404/409 - raised by Prism
{"detail": {"code": "bad_request", "message": "Endpoint host 'x' is not allowlisted."}}

// 422 - raised by FastAPI before the route runs
{"detail": [{"type": "missing", "loc": ["body", "name"], "msg": "Field required"}]}
```

So `body.detail` must never be used as the message — doing so renders
`"[object Object]"`. Handle both shapes:

```ts
function errorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown })?.detail;
  if (typeof detail === "string") return detail;                       // defensive
  if (Array.isArray(detail)) {                                         // 422
    const first = detail[0] as { loc?: unknown[]; msg?: string } | undefined;
    const field = Array.isArray(first?.loc) ? first.loc.at(-1) : undefined;
    return field ? `${field}: ${first?.msg ?? "invalid"}` : (first?.msg ?? `Request failed (${status})`);
  }
  const message = (detail as { message?: string })?.message;           // Prism errors
  return message ?? `Request failed (${status})`;
}
```

### Client timeouts

Do not use one short timeout for every route. `POST /connections/{id}/verify`
makes a **real model call**: measured N-ATLAS latency on a Tesla T4 is about
**8.3 s** per generation, a cold first call is slower, and the server's own
budget is `NATLAS_TIMEOUT_MS` (default 60 s, recommended 120 s against Colab).
A 20 s client abort will cancel legitimate verifications and report "the API
did not respond in time" when nothing is wrong.

Suggested: ~15 s for ordinary reads, **≥ 90 s** for `/verify`, and no timeout
(or a very long one) for an export download.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| `POST` | `/projects` | `{name, description?}` → 201 |
| `GET` | `/projects` | Caller's projects, newest first |
| `POST` | `/connections` | `{project_id, endpoint?, model_id?}` → 201. Omitted fields use server defaults. |
| `GET` | `/connections?project_id=` | Safe metadata only |
| `POST` | `/connections/{id}/verify` | Performs a **real** inference call. Slow (seconds). |
| `GET` | `/connections/{id}/gateway-health` | Diagnostics only — **never** show this as "integration verified" |
| `POST` | `/suites` | `{project_id, name, engine:"guard"\|"shield", description?}` → 201 |
| `GET` | `/suites?project_id=` | Summaries with `case_count` |
| `GET` | `/suites/{id}` | Suite **with** its cases |
| `POST` | `/test-cases` | → 201. Validated; see below. |
| `PATCH` | `/test-cases/{id}` | Partial update; bumps `version` |
| `POST` | `/runs` | → **202** `{run_id, status:"queued", total_cases}` |
| `GET` | `/runs?project_id=` | Last 100 runs |
| `GET` | `/runs/{id}` | Status + counts — **poll this** |
| `GET` | `/runs/{id}/results?limit=&offset=&state=` | Paginated case results |
| `GET` | `/traces?project_id=&run_id=&limit=&offset=` | Inference traces |
| `GET` | `/metrics/summary?project_id=&run_id=` | Pulse aggregates |
| `GET` | `/reports/{run_id}` | Full report JSON |
| `GET` | `/reports/{run_id}/export?format=json\|csv` | File download (`Content-Disposition`) |

`GET /health` (no prefix, no auth) is API liveness only.

## Shapes the UI needs to get right

### Connection

```json
{
  "id": "uuid", "project_id": "uuid", "provider": "natlas",
  "endpoint": "https://…", "model_id": "NCAIR1/N-ATLaS",
  "verification_state": "unverified",
  "verification_detail": null, "verified_at": null,
  "credential": "configured (****a1b2)",
  "created_at": "2026-10-11T12:00:00Z"
}
```

`verification_state` ∈ `unverified` | `verified` | `failed` | `blocked`.

**`credential` is already redacted — render it verbatim.** It is either
`"not configured"` or `"configured (****last4)"`. There is no endpoint that
returns a key, by design; do not add a field for one.

### Verify response

```json
{
  "connection_id": "uuid", "verified": false,
  "state": "blocked", "outcome": "blocked",
  "detail": "blocked: No N-ATLAS API key configured …",
  "model_id": null, "latency_ms": null, "upstream_status": null,
  "response_excerpt": null, "checked_at": "2026-10-11T12:00:00Z"
}
```

`outcome` ∈ `ok` | `auth` | `rate_limit` | `timeout` | `network` |
`upstream_error` | `schema` | `empty` | `not_found` | `bad_request` | `blocked`.

**Show `blocked` differently from `failed`.** Blocked means "not configured /
not permitted to call" — the user needs to supply a key or allowlist a host.
Failed means the call happened and the gateway rejected or broke. Never render
either as a success, and never label a `gateway-health` result as verification.

### Run

```json
{
  "id": "uuid", "status": "completed", "scoring_version": "1.0.0",
  "model_id": "NCAIR1/N-ATLaS", "total_cases": 20,
  "passed_count": 17, "failed_count": 3, "error_count": 0, "skipped_count": 0,
  "pass_rate": 0.85,
  "pass_rate_definition": "passed / (passed + failed); errored cases excluded",
  "error_summary": null,
  "created_at": "…", "started_at": "…", "completed_at": null
}
```

`status` ∈ `queued` | `running` | `completed` | `partially_completed` |
`failed` | `cancelled`.

**Four display rules that matter:**

1. `pass_rate` can be `null` — when nothing was scorable. Render "no scorable
   results", **never 0%**.
2. `error_count` is its own category. Do not fold it into failures, and do not
   put it in the pass-rate denominator. Showing `17/20` when 3 errored is wrong;
   it is 17 passed, 0 failed, 3 not scored.
3. `pass_rate_definition` ships in the payload — surface it near the number
   (tooltip or caption) so the denominator is never ambiguous.
4. `partially_completed` is a real, common state. It needs its own visual
   treatment, not the `completed` one.

### Run case

```json
{
  "run_case_id": "uuid", "name": "G01 exact answer - capital city",
  "engine": "guard", "category": "factual-exact", "severity": null,
  "state": "passed", "passed": true,
  "explanation": "Normalized output equals expected value (…).",
  "error": null, "error_kind": null,
  "score_metadata": {"rule": "guard.exact_match", "scoring_version": "1.0.0",
                     "attempts": 1, "successful_attempts": 1},
  "case_snapshot": {"name": "…", "user_prompt": "…", "evaluator_type": "…", "…": "…"},
  "traces": [{"trace_id": "uuid", "attempt": 1, "outcome": "ok",
              "upstream_status": 200, "latency_ms": 2210,
              "model_id": "NCAIR1/N-ATLaS", "response_text": "Abuja",
              "error_message": null, "recorded_at": "…"}]
}
```

`state` ∈ `queued` | `running` | `passed` | `failed` | `error` | `skipped`.

- **`passed` is `true` | `false` | `null`.** `null` with `state: "error"` means
  not scored. A tri-state badge, not a boolean.
- `explanation` is written for a human and says *why*. Show it next to the
  verdict — it is the product's whole value.
- `case_snapshot` is the case **as it ran**. Show it rather than re-fetching
  the live case, which may since have been edited.
- `traces` has one entry per attempt (a `consistency` case has several).

### Pulse summary

```json
{
  "inference": {"attempts": 22, "successful": 22,
                "by_outcome": {"ok": 22}, "transport_errors": 0,
                "auth_errors": 0, "blocked": 0},
  "latency_ms": {"population": "successful inference attempts only",
                 "sample_count": 22, "mean": 98.7, "median": 98.5,
                 "p95": 115, "min": 56, "max": 198,
                 "note": "Computed from 22 measured successful call(s), client-side."},
  "results": {"runs": 1, "passed": 20, "failed": 0, "errored_not_scored": 0,
              "pass_rate": 1.0, "pass_rate_definition": "…"},
  "models_seen": ["NCAIR1/N-ATLaS"],
  "data_source": "computed from inference_traces and test_runs rows; no synthetic data"
}
```

**Latency fields are `null` when `sample_count` is 0** — render the `note`, not
zeros. Always show `sample_count` beside a percentile: p95 from 3 calls is not
p95 from 3,000, and the UI should not imply otherwise.

### Export

`GET /reports/{id}/export?format=json|csv` returns the file with
`Content-Disposition: attachment`. CSV is UTF-8 with a BOM (opens correctly in
Excel) and one row per case. Trigger a download; do not try to render it.

## Rules for the frontend

These are not stylistic requests — they are what keeps the product honest, and
a judge will look for them.

1. **Never fabricate data on a judge-facing screen.** No placeholder KPI, no
   seeded chart, no "12,480 requests" where the API returned 22. If a value is
   absent, show an honest empty state. Every number in the UI must come from a
   response.
2. **Honest empty states.** A new project has no runs; say so. `models_seen: []`
   means none observed yet.
3. **`error` ≠ `failed`.** Distinct colour, distinct icon, distinct copy. Never
   count errors as failures.
4. **`blocked` is actionable, not broken.** Point at the fix: set
   `NATLAS_API_KEY`, or allowlist the host.
5. **Never display a credential**, and never add a field that would carry one.
6. **Shield results are test outcomes, not guarantees.** Do not label a passing
   Shield suite "secure". `inconclusive: true` in `score_metadata` must not be
   drawn as a confirmed vulnerability.
7. **Verification is slow.** `POST /verify` makes a real model call — seconds,
   up to the 60s timeout. Use a pending state; do not time out at 5s.
8. **Runs are polled.** `POST /runs` returns `queued` immediately; poll
   `GET /runs/{id}` (2s is reasonable) until `status` is terminal. There is no
   websocket.
9. **Show the scoring version** on a result view. Results from different
   versions are not strictly comparable.

## Suggested routes

Per the PRD: `/dashboard`, `/projects`, `/suites`, `/runs/new`, `/runs/[id]`,
`/results/[runId]`, `/pulse`, `/reports/[runId]`. Frontend structure, naming
and visual design are the frontend's call; these are the screens the API supports.

## Evaluator configuration (for the case editor)

Validated server-side on create and update — a case with no observable oracle
is rejected with `400`. Mirror these rules in the form to fail fast.

| `evaluator_type` | Required config | Optional |
|---|---|---|
| `exact_match` | `expected` | `lowercase`, `collapse_whitespace`, `strip_punctuation` |
| `keywords` | `required` and/or `forbidden` | `case_sensitive`, `whole_word` |
| `json_schema` | `schema` (JSON Schema object) | — |
| `consistency` | — (set `repeat_count` > 1) | `agreement_threshold`, normalization flags |
| `secret_disclosure` | `seeded_secrets` (fake literals) | `case_sensitive` |
| `refusal_expected` | `compliance_markers` and/or `refusal_markers` | — |
| `forbidden_action` | `forbidden_patterns` (valid regexes) | — |

`repeat_count` is 1–5. `max_concurrency` on a run is 1–8, further capped by the
server's `RUN_MAX_CONCURRENCY`.
