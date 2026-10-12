# Reporting and evidence export

Every evaluation run can be exported as reproducible evidence. This document
describes what a report contains, how to generate one, what is deliberately
redacted, and what the report does **not** claim.

## Generating a report

```bash
# Report data as JSON for rendering
GET /api/v1/reports/{run_id}

# Downloadable evidence
GET /api/v1/reports/{run_id}/export?format=json
GET /api/v1/reports/{run_id}/export?format=csv
```

Both require authentication and project-level authorisation: a run belonging to
another tenant returns 404, not 403, so the API never confirms the existence of
another tenant's ids.

In the application, use **Reports → export** on a completed run.

## What a JSON report contains

Produced by `services/api/app/reporting/exporter.py`, `report_version 1.0.0`:

| Section | Contents |
|---|---|
| Run summary | run id, status, counts of passed / failed / errored cases, pass rate and its definition, `scoring_version`, started and completed timestamps |
| Model metadata | the `model_id` actually reported by the gateway, the endpoint called, and the connection's verification state |
| Per case | `name`, `engine`, `category`, `severity`, `state`, `passed`, `explanation`, `error`, `error_kind`, the `scoring` metadata that produced the verdict, and the full `case_snapshot` |
| Findings | Shield findings with `category`, `severity`, `rule_id`, `evidence`, `mitigation` and `severity_rationale` |
| Traces | per attempt: `outcome`, `upstream_status`, `latency_ms`, `model_id`, `endpoint`, the response text, request and response metadata, and `recorded_at` |
| Limitations | an explicit block stating what the run does and does not establish |

`case_snapshot` is the immutable copy of the test as it was **when the run
executed** — prompts, evaluator type, evaluator config and expected outcomes.
Editing a test case afterwards does not change historical results. This is what
makes a report reproducible rather than merely recent.

CSV is a flattened one-row-per-case view of the same data, for spreadsheets and
quick review. The JSON export is the authoritative artifact; the CSV omits
traces and nested metadata.

Observed sizes for the 20-case baseline run: **JSON ≈ 73 KB, CSV ≈ 8.4 KB.**

## Redaction

Two kinds of sensitive content are removed, and both are enforced in the
exporter rather than left to callers:

1. **Credentials never appear.** Not in reports, not in traces, not in any API
   response. A connection's credential is rendered only as
   `configured (****last4)` or `not configured`. There is no endpoint that
   returns a stored key.
2. **Seeded Shield secrets are masked.** Shield's seeded-secret cases plant
   fake literals in order to detect disclosure. Those literals are redacted
   from explanations, errors, finding evidence, response text and the
   evaluator config in the export — otherwise the evidence file would itself
   publish the strings the test was checking for. A test asserts this.

## What a report does not claim

The limitations block is part of the artifact, not a disclaimer bolted on
afterwards. In particular:

- **A passing suite does not mean the model is safe or accurate.** It means the
  model satisfied the explicit, pre-declared oracles in that suite, on that
  run. See [evaluation-methodology.md](evaluation-methodology.md) for what each
  scorer does and does not prove.
- **Errors are not failures.** A service, network, rate-limit or parse problem
  is recorded as `error` and excluded from the pass rate, never counted as a
  passed security defence or a quality failure. Pass rate is
  `passed / (passed + failed)`, and the report states that definition inline.
- **If live inference was not verified for a run, the report says so.** A run
  executed with no credential records every case as `error` with
  `error_kind: blocked`, a null pass rate, and a limitations block stating that
  live inference was not verified. Prism does not produce an optimistic report
  from a run that never reached a model.
- **Latency is measured client-side** and includes network time between the
  API and the inference host.
- **Pass rate is not stable across runs.** Generation is sampled
  (`temperature` defaults to 0.7); the same 20 cases against the same model
  produced 0.75, 0.75 and 0.80 on three runs. Quote a run id, or use
  `repeat_count` to measure across repeats. A single pass rate is not a
  property of N-ATLAS.

## Committed evidence

Timestamped artifacts from live verification runs are committed under
[`../services/api/docs/integration-evidence/`](../services/api/docs/integration-evidence/):
stage-by-stage verification records, full JSON and CSV report exports, and
console logs. They were scanned for credentials before committing; the only
occurrence of any key is the intended `configured (****last4)` redaction.

These artifacts do not depend on the model host staying available. Runs, traces,
metrics and exports are read from PostgreSQL, so the evidence remains
verifiable after a GPU endpoint is shut down.
