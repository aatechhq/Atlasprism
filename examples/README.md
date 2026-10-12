# Examples

Two things that are **not** part of ATLAS Prism, kept here because the
black-box documentation is hard to follow without them.

## `acme-assistant-worker/` — an application under test

A deliberately small AI application built on N-ATLAS: a bank support
assistant with its own system prompt, its own access-code guardrail, and its
own upstream credential held server-side. It is deployed separately from
Prism, which is the point — Prism cannot see its prompt and can only observe
what the endpoint says. That is what makes a black-box test a black-box test.

Two routes do the work:

| Route | Purpose |
|---|---|
| `GET /.well-known/atlas-prism-verification.txt` | Publishes the ownership token. Only someone who controls the host can serve content here, which is the entire basis of the file verification method. |
| `POST /v1/chat/completions` | OpenAI-compatible. Prepends the application's own system prompt, forwards to N-ATLAS with the upstream key attached server-side, and returns the response. |

Deliberately **unauthenticated**: Prism sends no credential to a third-party
endpoint, so a black-box target must accept unauthenticated requests. See
§5.3 of the technical documentation for why.

`GUARDRAIL_MODE` selects which version of the application's instructions is
live — `weak` or `hardened`. That variable is the entire demonstration: run
Shield against `weak` to find a real disclosure, flip to `hardened`, re-run,
and compare. **The fix is a change to the application, not to Prism**, which
is the argument for testing the application rather than the model.

```bash
cd examples/acme-assistant-worker
npx wrangler secret put NATLAS_BASE_URL     # the inference endpoint
npx wrangler secret put NATLAS_API_KEY      # the upstream key
npx wrangler deploy
```

The ownership token is a **var**, not a secret — it is published at a
well-known URL by design, so calling it a secret would be theatre. Set
`PRISM_VERIFICATION_VALUE` in `wrangler.toml` to the value Prism issues, then
deploy.

When its upstream is unreachable the app returns `502` with the reason rather
than hanging or inventing an answer. Prism records that as `upstream_error` —
an error, excluded from the pass rate, never a failed test.

## `seed_demo.py` — builds the demonstration account

Creates the organisation, a versioned dataset, two projects, suites, and the
runs behind the worked security case, then prints every figure back from the
API. **Safe to run repeatedly**: every step looks before it creates, so a
second run completes what is missing rather than duplicating it.

It requires the GPU host to be awake, and checks that first: with the model
asleep it stops before changing anything rather than filling an account with
errors.

Nothing in it is fabricated. If the weak prompt does not disclose on a given
run, it says so instead of relabelling a pass as a finding — generation is
sampled, and a seeded account that claims a finding it did not produce would
be worse than no seeded account at all.
