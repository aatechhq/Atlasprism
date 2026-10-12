# Beta testing and external validation

PS1 requires independent developers to use the tool and provide feedback. This
document records the assessment that was carried out, and states precisely what
that record contains and what it does not — so that a reader can judge its
weight rather than infer it.

## Assessment summary

> *The following is the assessment as supplied by the project owner (AA
> Technologies). It is reproduced here as the record of the beta-testing round;
> it was not authored or verified by the engineering tooling that produced this
> repository.*

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

## Feedback accepted, and its status

| Feedback | Status in this repository |
|---|---|
| Clearer explanations of security severity | **Not implemented.** Shield findings carry `severity` and `severity_rationale` fields and the baseline cases populate them, but the application does not yet present severity with an explanation in the interface. |
| More detailed error messages for troubleshooting | **Partially implemented.** The API returns structured errors with a `code` and an actionable `message`, and run cases record an `error_kind` separate from evaluation failure. Guidance for diagnosing a failed deployment is in [deployment-api.md](deployment-api.md). No further work was done in response to this specific item. |
| Improvements to onboarding | **Partially addressed.** Suite JSON import was added so a developer can populate a suite without writing API calls by hand. A per-case editor is still missing — see *What is still missing* below. |
| Improvements to reporting | **Not implemented beyond what already existed.** Reporting is documented in [reporting.md](reporting.md); no change was made in response to this item. |

Listing these as open rather than closed is deliberate. Describing accepted
feedback as implemented when it is not would be the same category of error this
project avoids elsewhere.

## What this record does not contain

Stated plainly, because a reader assessing independence is entitled to know:

- **The testers are not identified in this repository**, and no dated,
  countersigned consent record is committed here. The project owner holds the
  supporting material — API logs, screenshots, evaluation reports and written
  developer feedback — and it forms part of the competition submission package
  rather than the public repository.
- **The assessment is a summary**, not a transcript. It carries no verbatim
  tester quotes, no session dates and no per-session evidence links.
- **The engineering tooling that produced this repository did not observe the
  sessions** and cannot attest to them. It records them.

If the submission requires dated consent and identified testers, that evidence
must come from the project owner's package; this document is not a substitute
for it.

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

## What is still missing

- A **per-case test editor** in the application. PRD §2 screen 03 specifies
  "test editor, JSON import"; JSON import exists, the editor does not.
  `POST /test-cases` and `PATCH /test-cases/{id}` are implemented server-side
  and unused by the interface.
- An **application profile** — a system prompt and policy defined per project
  that every run applies. Without it Prism evaluates the model directly rather
  than the developer's application, which is the subject the product blueprint
  describes.
- **Run-to-run comparison / regression view.** Each run is currently
  independent; nothing surfaces which cases changed status between two runs.
- **Severity presentation** in the interface, per the feedback above.
