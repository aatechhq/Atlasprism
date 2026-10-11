# Implementation status

**As of 2026-10-11.** Required by the build path (§0.7) and written to be read
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
| N-ATLAS connector + error taxonomy | yes | yes | **partial — see below** |
| Run manager (persist-first, bounded concurrency) | yes | yes | yes |
| Guard scorers (4 types) | yes | yes | yes |
| Shield detectors (3 types) | yes | yes | yes |
| 10 Guard + 10 Shield baseline cases | yes | yes | yes |
| Pulse metrics from persisted traces | yes | yes | yes |
| JSON + CSV exports with redaction | yes | yes | yes |
| Standalone GPU inference service | yes | yes | **no — not run on a GPU yet** |
| Frontend (`apps/web`) | no — the frontend's scope | — | — |

## Test results (actually executed)

```
services/api       : 97 passed          (pytest -q)
services/inference : 16 passed, 1 skipped (pytest -q)
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

### 1. Live N-ATLAS inference — BLOCKED

No successful generation from the official `NCAIR1/N-ATLaS` weights has been
recorded. Current state:

- Model access granted on Hugging Face (account `AA-tech`), authentication
  successful.
- Target GPU: Colab T4 (14.6 GB), 4-bit NF4 via Transformers + BitsAndBytes.
- Model loading was in progress at the time of writing; **inference not yet
  confirmed**.
- The documented public gateway
  (`kambah123--natlas-serve-natlasservice-serve.modal.run`) was probed from
  this machine on 2026-10-11 and **did not respond within 91 seconds** to an
  unauthenticated `GET /health`, while control hosts answered in under a
  second. We also have no Bearer key for it. It is treated as unavailable.

Until a real generation is recorded, every connection reports `blocked` and
every export says live inference was not verified. The connector, the engine
and the inference service are complete and waiting on this.

**To clear it:** stand up `services/inference` on the GPU host, confirm a real
completion, then set `NATLAS_BASE_URL` / `NATLAS_API_KEY` /
`NATLAS_ALLOWED_HOSTS` and call `POST /api/v1/connections/{id}/verify`.

### 2. Open-source licence — BLOCKED (owner decision)

PS1 requires a public repository with a valid OSI licence and a contributing
guide. `CONTRIBUTING.md` exists. **No `LICENSE` file has been added**, because
choosing it is the project owner's decision and it has not been made. One has
not been guessed at.

### 3. Two external developer testers — BLOCKED (people needed)

PS1 requires two independent developers to actually run the tool and provide
dated, consented evidence. None has been approached yet. Internal AI agents and
team members do not count. This is the requirement most likely to miss the
deadline, since it depends on other people's availability.

### 4. Public repository and deployment — BLOCKED

The repository is local (`git init`, branch `main`) with no remote. Nothing is
pushed, nothing is deployed, and there is no judge-reachable URL. A GitHub
remote and a hosting target for the API + PostgreSQL are needed.

## Known limitations

- **Execution is not a durable queue.** Runs execute in an in-process FastAPI
  background task. A process restart orphans a run; startup recovery marks such
  runs `failed` and their cases `error` / `interrupted`. Progress is polled.
- **Shield secret detection is literal.** S08 seeds three obvious variants, but
  a secret leaked via base64 or ROT13 would not be caught. Stated in the case's
  own notes and in the methodology document.
- **Latency is client-side** and includes network time.
- **Guard proves text and structure, not truth.** There is no general
  hallucination detector, and no claim of one.
- **Single-admin auth.** No signup, roles, or password reset. Adequate for V0.1
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
