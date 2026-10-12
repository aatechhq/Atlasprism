# Beta testing and external validation

ATLAS Prism was assessed by two independent developers covering usability,
N-ATLAS integration, reliability testing, security evaluation, performance
monitoring and reporting. This document records that assessment, how the
feedback was handled, and the independent technical verification that
accompanies it.

## Assessment summary

ATLAS Prism underwent a beta-testing assessment covering usability, N-ATLAS
integration, reliability testing, security evaluation, performance monitoring
and reporting from two developer perspectives.

**Beta Tester 1 (AI Application Developer)** assessed the interactive
playground, Shield security testing, Pulse monitoring and results export. The
assessment highlighted accessible testing workflows, useful performance metrics
and security evaluation capabilities. Clearer explanations of security severity
were identified as an improvement opportunity.

**Beta Tester 2 (Backend Developer)** assessed N-ATLAS API configuration,
connectivity, Guard evaluations and reporting. Key considerations included
straightforward integration, understandable evaluation results and structured
reporting. More detailed error messages were recommended to improve
troubleshooting.

**Technical validation** confirmed successful N-ATLAS authentication, GPU
inference and model-generated responses. GPU provisioning and authentication
issues encountered during implementation were resolved.

Overall, the assessment identified improvements in onboarding, evaluation
clarity, diagnostic feedback and reporting. Supporting evidence includes API
logs, screenshots, evaluation reports and developer feedback.

## How the feedback was handled

| Feedback | Status in this repository |
|---|---|
| Clearer explanations of security severity | Severity and `severity_rationale` are captured per finding and carried into reports and exports. Surfacing that rationale in the interface is scheduled for V0.5. |
| More detailed error messages for troubleshooting | Addressed. The API returns structured errors with a `code` and an actionable `message`, and every run case records an `error_kind` distinct from an evaluation failure — so a service problem is never reported as a model failure. Deployment diagnostics are documented in [deployment-api.md](deployment-api.md). |
| Improvements to onboarding | Addressed. Suite JSON import was added, so a developer can populate a suite from a dataset file without writing API calls by hand. |
| Improvements to reporting | Reporting is documented in full in [reporting.md](reporting.md) — report sections, both export formats, redaction rules and stated limitations. |

## Supporting material

The testers' written feedback, API logs, screenshots and evaluation reports are
held with the competition submission package rather than in the public
repository, since they include session detail and tester identities.

## Independent technical verification that *is* in this repository

Separate from the beta assessment above, the integration was verified by
driving the deployed system and the artifacts were committed:

| | |
|---|---|
| Claim | `POST /api/v1/connections/{id}/verify` returned `verified: true` |
| When | 2026-10-11T23:25:27Z |
| Driven by | the deployed API at `atlas-prism-api.fly.dev`, authenticated as a signed-in web user |
| Model | `NCAIR1/N-ATLaS` on Lightning AI (Tesla T4, 4-bit NF4) |
| Measured | 925 ms generation, `upstream_status: 200` |
| Followed by | run `82d37773-1ef0-49ce-b03d-958459acae81` — 20 cases, 16 passed, 4 failed, 0 errors, 22/22 successful inference attempts, JSON and CSV exports |

Artifacts:
[`../services/api/docs/integration-evidence/`](../services/api/docs/integration-evidence/).

This is machine-verifiable and reproducible. The beta assessment above is
human testimony. They are different kinds of evidence and this document keeps
them apart.

## Roadmap beyond V0.1

V0.1 is scoped as one working evaluation pipeline demonstrating three
capabilities. The following are the next increments, in the order they add the
most value:

- **Per-case test editor.** `POST /test-cases` and `PATCH /test-cases/{id}` are
  implemented and documented in [api-contract.md](api-contract.md); V0.5 adds
  the editing surface over them, alongside the JSON import already shipped.
- **Application profiles.** A system prompt and policy defined once per project
  and applied to every run, so a team evaluates the assistant they built rather
  than the base model — and Shield attempts to override *their* rules.
- **Run-to-run comparison.** Each run already stores an immutable snapshot of
  its configuration, which is what a regression view needs: show which cases
  changed status after a prompt or model change. This is the basis of the
  release-gating workflow.
- **Severity rationale in the interface**, per the tester feedback above.
