# prism — ATLAS Prism CLI

Run an evaluation gate inside a release pipeline. One file, standard library
only, no install step.

```bash
python prism.py --help
```

## Authentication

| Deployment | How |
|---|---|
| Any (including Neon Auth) | `--token` or `$PRISM_TOKEN` |
| Local mode (`AUTH_MODE=local`) | `--email` / `--password`, or `$PRISM_EMAIL` / `$PRISM_PASSWORD` |

A deployed Prism using Neon Auth will **not** accept a password-login token on
protected routes. Use `--token` there; obtain it from `GET /api/auth/token`
while signed in.

`$PRISM_API` sets the API base URL (default `https://atlas-prism-api.fly.dev`).

## Exit codes — the CI contract

| Code | Meaning |
|---|---|
| `0` | **pass** — thresholds met, the release may proceed |
| `1` | **block** — a declared threshold was not met |
| `2` | **not_configured** — no thresholds set, so no decision was made |
| `3` | **inconclusive** — the run produced no scored evidence |
| `4` | usage or transport error |

**`not_configured` is deliberately not `0`.** A pipeline that silently passes
because nobody set a threshold is worse than one that fails loudly.

`compare` exits `1` when any case regressed. `findings` exits `1` when the run
produced any finding.

## Commands

```bash
prism projects
prism suites  --project <id>
prism runs    --project <id> [--limit 20]

prism verify  --connection <id>          # proves live model access

prism run     --project <id> --connection <id> \
              --suite <id> [--suite <id> ...] \
              [--concurrency 1] [--gate] [--no-wait] [--quiet]

prism gate     --run <id>
prism compare  --run <id> --baseline <id>
prism findings --run <id>
prism export   --run <id> --format json|csv [--out report.json]
```

`run --gate` waits for completion and then evaluates the release gate, so a
pipeline step is a single command.

## Example: block a pull request on a failing gate

`.github/workflows/ai-assurance.yml`:

```yaml
name: AI assurance

on: [pull_request]

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }

      - name: Run Guard and Shield against the application
        env:
          PRISM_API: ${{ secrets.PRISM_API }}
          PRISM_TOKEN: ${{ secrets.PRISM_TOKEN }}
        run: |
          python tools/prism-cli/prism.py run \
            --project    ${{ vars.PRISM_PROJECT }} \
            --connection ${{ vars.PRISM_CONNECTION }} \
            --suite      ${{ vars.PRISM_GUARD_SUITE }} \
            --suite      ${{ vars.PRISM_SHIELD_SUITE }} \
            --gate | tee prism.out
          echo "RUN_ID=$(tail -n2 prism.out | head -n1)" >> "$GITHUB_ENV"

      - name: Archive the evidence
        if: always()
        env:
          PRISM_TOKEN: ${{ secrets.PRISM_TOKEN }}
        run: |
          python tools/prism-cli/prism.py export \
            --run "$RUN_ID" --format json --out prism-report.json

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: prism-evidence
          path: prism-report.json
```

The job fails when the gate blocks, and the evidence is archived either way —
which is the point. A blocked release that leaves no record is hard to argue
with; one with an attached report is a conversation about specific cases.

## Guarding against a regression instead of a threshold

If you would rather gate on *change* than on an absolute pass rate, compare
against the last known-good run:

```bash
python tools/prism-cli/prism.py compare \
  --run "$NEW_RUN" --baseline "$KNOWN_GOOD_RUN"
```

It exits `1` if any case regressed, and prints a warning when a change was
measured from a single generation on each side — because generation is sampled
and such a flip may be variance rather than a real regression. Raise
`repeat_count` on those cases before treating the result as decisive.

## A caution worth reading before you automate this

A run costs real inference time. Against a single GPU serving one generation at
a time, a 20-case suite takes minutes. Running the full suite on every commit of
a busy repository will queue, and it will cost. Sensible defaults:

- gate pull requests on a **small** Shield suite, and run the full set nightly
- keep `--concurrency 1` against a single-GPU host; higher values only queue
- use `--no-wait` when you want to launch and collect results in a later step
