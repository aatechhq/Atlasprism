# Contributing to ATLAS Prism

## Ground rules

These are not style preferences. They are what makes the tool's output worth
trusting, and a change that breaks one of them will not be merged.

1. **Never simulate inference and present it as real.** Mocks and fixtures are
   for unit tests only. No stub, canned response or placeholder metric may
   appear on an endpoint or screen a user or judge sees. `FakeConnector`
   refuses to instantiate unless the test flag is set — keep it that way.
2. **An error is not a failure.** If a model did not respond, the case state is
   `error` with `passed = NULL`. It is never a failed quality test and never a
   passed security defense. Pass rate is `passed / (passed + failed)`, with
   errors reported separately.
3. **Every result must trace to evidence.** A finding references a test case, a
   scorer rule, a recorded request/response, timestamps and a run id.
4. **No secret in any output.** Not in a response, a log, an export, a commit
   or a screenshot. Only "configured" and the last four characters may ever be
   shown. Shield cases seed FAKE secrets; the exporter redacts those too.
5. **Say what was verified.** Distinguish implemented, automated-tested and
   live-verified. Never report "complete" for a passing type-check, a green
   test suite or a reachable `/health`.
6. **Keep it small.** No microservices, Kubernetes, event buses, or generic
   frameworks. Straightforward modules and functions.

## Development

```bash
cd services/api
uv venv .venv && uv pip install --python .venv -e ".[dev]"
.venv/bin/alembic upgrade head
.venv/bin/python -m pytest -q
```

Docker must be running: the tests create and drop real PostgreSQL databases.

### Adding a scorer

1. Write the function in `app/evaluation/scoring.py`. It takes
   `(output: str, config: dict)` and returns a `ScoreResult` with `passed`, a
   human-readable `explanation` that states *why*, a stable `rule` name, and
   `metadata` carrying the inputs that decided it.
2. Register it in `SCORERS`.
3. Add required-key validation in `app/api/v1/suites.py::_validate_evaluator`
   so a misconfigured case is rejected at write time, not mid-run.
4. Unit-test the pass case, the fail case, and at least one edge case.
5. If the rule's behaviour changes, bump `SCORING_VERSION` — stored runs record
   the version that produced them.

### Adding a Shield case

Every case needs an **objective detector**: a seeded fake secret literal, an
explicit compliance marker, or a structured forbidden pattern. Compromise must
never be inferred from tone or vocabulary. Include a `severity` and a written
`severity_rationale`. Use only fabricated secrets, and target only a model
connection the operator configured for their own project.

### Database changes

Edit `app/models/entities.py`, then:

```bash
.venv/bin/alembic revision --autogenerate -m "what changed"
.venv/bin/alembic upgrade head
```

Review the generated migration before committing it, and confirm it applies to
a blank database (`tests/test_migrations.py` covers this).

### API changes

The frontend is built against `docs/api-contract.md`. Update that document in
the same change, and say so in the PR description — the frontend owner needs to
know before the route changes under them. Do not change a response shape
silently.
