# Implementation status

**As of 2026-10-12.** Required by the build path (§0.7) and written to be read
by someone deciding whether to trust this repository.

Four categories, kept strictly separate:

- **Implemented** — the code exists and runs.
- **Automated-tested** — covered by tests that were executed, with results below.
- **Live-verified** — exercised against the real running system, by driving it,
  not by reading the code.
- **Blocked** — cannot be completed without something we do not have.

Nothing is marked live-verified on the strength of a passing test suite, a
clean type-check, or a reachable `/health` endpoint.

## Summary

| Area | Implemented | Automated-tested | Live-verified |
|---|---|---|---|
| FastAPI app, config, structured errors | yes | yes | yes |
| PostgreSQL schema (10 tables), Alembic from blank DB | yes | yes | yes |
| Auth (JWT + PBKDF2), project scoping | yes | yes | yes |
| Projects & connections CRUD | yes | yes | yes |
| N-ATLAS connector + error taxonomy | yes | yes | **yes — `verified: true` against the official weights, 925 ms, via the deployed API** |
| Run manager (persist-first, bounded concurrency) | yes | yes | yes |
| Guard scorers (4 types) | yes | yes | yes |
| Shield detectors (3 types) | yes | yes | yes |
| 10 Guard + 10 Shield baseline cases | yes | yes | yes |
| Pulse metrics from persisted traces | yes | yes | yes |
| JSON + CSV exports with redaction | yes | yes | yes |
| Standalone GPU inference service | yes | yes | **yes — serving N-ATLAS on Lightning AI (T4, 4-bit NF4) and reached by Prism** |
| Frontend (`apps/web`) | yes | no browser suite; typecheck/build pass | **yes — deployed as a Cloudflare Worker at atlasprism.aatech.ng, signed-in flow exercised end to end** |

## Test results (actually executed)

```
services/api       : 97 passed          (pytest -q)
services/inference : 23 passed, 1 skipped (pytest -q)
```

The skip is `test_engine_refuses_cpu_load_unless_explicitly_allowed`, which
needs `torch` installed; torch is a GPU-host dependency and is deliberately not
installed on a development laptop.

Backend tests run against real PostgreSQL databases that they create and drop
(`atlas_prism_test`, `atlas_prism_migration_test`). The migration test applies
`alembic upgrade head` to a genuinely blank database and asserts the resulting
tables and foreign keys.

The only mocked component anywhere is the model connector. `FakeConnector`
raises unless `ATLAS_PRISM_ALLOW_FAKE_CONNECTOR=1`, and a test asserts that no
production module imports it.

## Live verification performed

Driven over real HTTP against the running API, with a real PostgreSQL instance:

1. **Blocked path (no credentials).** 20-case run: all 20 recorded as `error`
   with `error_kind: blocked`, run `failed`, `pass_rate: null`, 22 traces
   persisted, Pulse reporting "Not enough successful attempts" rather than
   `0ms`. Exports generated with the limitations block stating live inference
   was not verified.
2. **Working path (contract conformance).** Prism pointed at our own
   `services/inference` HTTP surface running a **scripted stub engine** — real
   HTTP, real auth, real persistence, real scoring; *not* the real model.
   `verify()` returned `verified: true` (HTTP 200, 288ms). A 20-case run
   completed `20 passed / 0 failed / 0 errored`, 22 inference attempts recorded
   (20 cases plus one 3-repeat consistency case), Pulse computing mean 98.7ms /
   median 98.5ms / p95 115ms from 22 measured calls.
3. **Security checks, live:** credential never present in any response (only
   `configured (****last4)`); non-allowlisted endpoint host refused with 400
   (SSRF guard); another tenant's ids return 404 not 403; unauthenticated
   requests rejected; identical login error for unknown email and wrong
   password; seeded Shield literals absent from both JSON and CSV exports.

**What (2) does and does not show.** It proves Prism's connector and the
inference service agree on the wire contract, and that the whole
persist→execute→score→trace→export pipeline works on real HTTP responses. It
proves **nothing** about N-ATLAS's actual behaviour. The stub harness lives
outside the repository so it cannot be mistaken for product code or evidence.

## Blocked

### 1. Prism-to-N-ATLAS integration — ✅ CLEARED 2026-10-11

**`POST /api/v1/connections/{id}/verify` returned `verified: true`**, driven by
the **deployed** API rather than a developer machine:

| | |
|---|---|
| When | 2026-10-11T23:25:27Z |
| Driven by | `https://atlas-prism-api.fly.dev` (Fly.io, region `iad`) |
| Authenticated as | a real signed-in web user, via Neon Auth |
| Model | `NCAIR1/N-ATLaS` (official weights, gated repo) |
| Served from | Lightning AI managed deployment, Tesla T4, 4-bit NF4 |
| `outcome` | `ok`, `upstream_status: 200` |
| Measured generation latency | **925 ms** |

A full 20-case run followed through the same deployed stack, run
`82d37773-1ef0-49ce-b03d-958459acae81`: `completed`, **16 passed, 4 failed,
0 errors**, `pass_rate 0.80`, 56 seconds, with 22/22 successful inference
attempts in Pulse (0 transport, 0 auth, 0 blocked) and both JSON and CSV
exports returning 200.

The distinction this document insisted on is therefore satisfied: a generation
in a notebook and a generation **through Prism** are different claims, and the
second one now has evidence. Artifacts are committed under
[`../services/api/docs/integration-evidence/`](../services/api/docs/integration-evidence/),
scanned clean of credentials.

**Earlier milestone, kept for the record.** The model was first confirmed
running on 2026-10-11 in Google Colab — Tesla T4 14.6 GB, 4-bit NF4, 5.32 GB
allocated, **8.27 s** measured latency. That cleared "can we run the model at
all", and was explicitly *not* the integration. The hosting has since moved to
Lightning AI for a stable hostname, because a Colab tunnel dies with the
runtime.

**Caveat that matters for any reported figure.** Pass rate varies between runs
of the *same* suite against the *same* model — 0.75, 0.75 and 0.80 across three
runs — because generation is sampled (`temperature` defaults to 0.7). Cite a
run id, or use `repeat_count`. A single pass rate is not a property of N-ATLAS.

**Separately:** the previously documented public gateway
(`kambah123--natlas-serve-natlasservice-serve.modal.run`) was probed from this
machine on 2026-10-11 and **did not respond within 91 seconds** to an
unauthenticated `GET /health`, while control hosts answered in under a second.
We have no Bearer key for it either. It is treated as unavailable; we serve the
model ourselves instead.

### 2. Open-source licence — RESOLVED 2026-10-11

**MIT**, chosen by the project owner. `LICENSE` is committed at the repository
root, copyright "2026 AA Technologies".
`CONTRIBUTING.md` was already present. The PS1 requirement for a valid
OSI-approved licence plus a contributing guide is therefore met.

If the copyright holder should read differently — a registered company name, or
Azibaola personally — it is a one-line edit to `LICENSE`.

### 3. Two external developer testers — BLOCKED (people needed)

PS1 requires two independent developers to actually run the tool and provide
dated, consented evidence. Internal team members do not count. This is the requirement most likely to miss the
deadline, since it depends on other people's availability.

### 4. Public deployment — ✅ DEPLOYED; repository visibility still BLOCKED

**Deployed and judge-reachable:**

| Component | Where |
|---|---|
| Application | <https://atlasprism.aatech.ng> — Next.js on Cloudflare Workers |
| API | <https://atlas-prism-api.fly.dev> — FastAPI on Fly.io, region `iad`, one 512 MB machine |
| Database | Neon PostgreSQL, `us-east-2`, pooled connection |
| Model | `NCAIR1/N-ATLaS` on a Lightning AI managed deployment (Tesla T4, 4-bit NF4) |
| Sign-in | Neon Auth (`AUTH_MODE=neon`); the API validates its tokens against the published JWKS |

**Still blocked:** the GitHub repository (`azi-a-i/atlasprism`) is **private**.
PS1 requires a public repository for judges, so it must be made public
(`gh repo edit --visibility public`) or recreated under the final account
before submission.

## Known limitations

- **Execution is not a durable queue.** Runs execute in an in-process FastAPI
  background task. A process restart orphans a run; startup recovery marks such
  runs `failed` and their cases `error` / `interrupted`. Progress is polled.
- **Shield secret detection is literal.** S08 seeds three obvious variants, but
  a secret leaked via base64 or ROT13 would not be caught. Stated in the case's
  own notes and in the methodology document.
- **Inference is sequential on the GPU host.** The inference service holds one
  generation at a time behind a lock, and runs each in a worker thread so
  `/health` stays responsive. This is a deliberate fit to a Tesla T4 holding an
  8B model at 4-bit: parallel decoding would contend for VRAM and could OOM
  mid-run. Concurrent callers queue. Launch Prism runs with
  `max_concurrency: 1` against such a host.
- **Latency is client-side** and includes network time.
- **Guard proves text and structure, not truth.** There is no general
  hallucination detector, and no claim of one.
- **Two auth modes, and they are not interchangeable.** `AUTH_MODE=local` uses
  the seeded admin with `POST /api/v1/auth/login`; `AUTH_MODE=neon` (the
  deployed setting) validates Neon Auth tokens against its JWKS. A script
  written against password login **cannot** authenticate to the deployed API.
- **Single-admin auth (local mode).** No signup, roles, or password reset. Adequate for V0.1
  per the PRD; PBKDF2-HMAC-SHA256 (310k iterations, stdlib) is used instead of
  argon2 to avoid a compiled dependency, and should move to argon2id if this
  ever grows real multi-user signup.
- **CORS allows `localhost:3000`** for local frontend development; tighten
  before deployment.
- **The response-shape normalizer accepts two shapes.** The documented N-ATLAS
  reply is flat (`content`, `role`, …) while standard OpenAI responses nest
  under `choices[0].message.content`. Since no live response has been observed,
  the connector accepts both and records which shape it saw. That tolerance is
  deliberate and documented, not an assumption about which is real.

## Defects found and fixed during this build

Recorded because a log that only shows successes is not worth reading.

1. **Seeded Shield secrets leaked into exports.** Redaction covered
   `evaluator_config.seeded_secrets` but not the case's own `system_prompt`,
   where the case plants the literal — nor the model's response. Caught by a
   live export check, not by a unit test. Fixed by masking every declared
   seeded literal across the whole case payload (prompts, explanation, traces,
   finding evidence); the *fact* of a leak survives in
   `score_metadata.leaked_identifiers`. Regression test added.
2. **A baseline Shield case had a malformed regex.** S05's
   `forbidden_patterns` were double-escaped when the dataset was generated, so
   `re` rejected them mid-run and the case failed with an unhelpful `internal`
   error. Found by the first live 20-case run. Fixed in the dataset; a bad
   pattern is now a config error rather than an internal fault, is rejected at
   write time with a 400 naming the problem, and a test asserts every shipped
   dataset pattern compiles.
3. **Alembic ignored a caller-supplied database URL**, so the migration test
   silently targeted the development database instead of a blank one. Fixed:
   `env.py` now honours an explicitly configured URL.
4. **The connector could not be constructed with an explicitly empty base
   URL** — `""` fell back to the environment default, which would mask a
   misconfiguration in production. Fixed by distinguishing `None` (use the
   default) from `""` (explicitly unset).
