# Running the N-ATLAS inference service persistently on Lightning AI

Supersedes the Colab path in [`colab_launch.md`](colab_launch.md) for anything
judge-facing. A Colab quick tunnel dies with the runtime and changes hostname
on every restart; a Lightning deployment keeps one stable HTTPS hostname, which
is what Prism's host allowlist and the NAIC evidence need.

**Nothing in `natlas_inference/` changes.** The service already does what a
persistent deployment requires:

- `PRELOAD=1` (the default) loads `NCAIR1/N-ATLaS` **once at startup** and keeps
  it resident in GPU memory, so no request pays the load cost.
- `GENERATION_LOCK` serialises generation — a T4 holding an 8B model at 4-bit
  has no headroom for concurrent decoding, so requests queue rather than OOM.
- `require_auth` enforces `Authorization: Bearer $INFERENCE_API_KEY` on both
  `/v1` routes, and the service **refuses to start without a key** ("it would be
  an open proxy to a GPU").

So this document adds one thin start script and the platform settings. There is
one implementation to audit, not two.

---

## 0. File changes required: **none in the service**

`attach_preloaded()` is the *optional* Colab path, not the default. The
service already loads the model itself at startup. Verify it yourself rather
than taking this on trust:

| Requirement | Already satisfied by | Evidence |
|---|---|---|
| Load `NCAIR1/N-ATLaS` once at startup, 4-bit NF4 | `natlas_inference/app.py` lifespan | lines 99–108 construct `TransformersEngine` and call `.load()` when `PRELOAD` is on |
| 4-bit NF4 is the default | `natlas_inference/config.py` | `LOAD_IN_4BIT` defaults to `"1"` (line 28); `engine.py` builds `BitsAndBytesConfig(nf4, double_quant, bfloat16)` |
| Preload is the default | `config.py` | `PRELOAD` defaults to `"1"` (line 31) |
| Serve through the existing authenticated endpoints | `app.py` | `/v1/models` and `/v1/chat/completions` carry `dependencies=[Depends(require_auth)]`, untouched |
| Env vars for HF auth + inference key | `config.py` lines 25–26 | `INFERENCE_API_KEY`, `HF_TOKEN` read from the environment |
| One inference at a time | `app.py` | `GENERATION_LOCK = asyncio.Lock()`, held across every generation |
| Preserve Prism's expected response format | — | **no code was changed**, so the contract cannot have drifted |

The model stays resident because `TransformersEngine.load()` is a no-op once
loaded (`if self.loaded: return`) and the engine is a module-level singleton.

**The only thing missing for a persistent deployment was packaging and
documentation.** Two files were added, neither of which touches the service:

- `run_lightning.sh` — a thin, fail-fast start script
- `Dockerfile` — a GPU container for a managed inference platform

### Switching off the Colab path

Nothing to switch off. `attach_preloaded()` is only invoked if *you* call it
from a notebook. In a Studio or container you never do, so the lifespan hook
takes the auto-load branch. The two paths share
`TransformersEngine.generate`/`_build_prompt` by assignment at the bottom of
`engine.py`, so they cannot drift apart.

---

## 1. Environment

Set these as Lightning **secrets/environment variables**, never in a file in
the repo:

| Variable | Value | Why |
|---|---|---|
| `INFERENCE_API_KEY` | a long random string | The only thing protecting a public GPU endpoint. Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. |
| `HF_TOKEN` | your Hugging Face token | `NCAIR1/N-ATLaS` is gated. |
| `HF_HOME` | a **persistent** path | Without this an 8B model re-downloads on every restart. On Lightning use a path under your persistent studio storage (e.g. `/teamspace/studios/this_studio/.cache/huggingface`) — confirm the exact path on your studio. |
| `MODEL_ID` | `NCAIR1/N-ATLaS` | Optional; this is the default. |
| `LOAD_IN_4BIT` | `1` | Optional; default. NF4 + double quant, ~6 GB VRAM. |
| `MAX_NEW_TOKENS` | `256` | Optional; default. Hard server-side cap — a client cannot exceed it. |
| `PORT` | `8000` | Optional; the start script honours it if the platform injects one. |

`ALLOW_CPU` stays unset (`0`): the service should refuse to start if CUDA is
missing rather than silently serving at unusable speed.

## 2. Dependencies

The GPU stack is an optional extra, kept out of the Prism backend on purpose:

```bash
cd services/inference
pip install -e ".[gpu]"
```

If the studio already has torch/transformers/bitsandbytes (yours does), the
base install is enough:

```bash
pip install -e .
```

## 3. Exact startup command

```bash
cd services/inference
bash run_lightning.sh
```

That is the whole command. `run_lightning.sh` fails fast if
`INFERENCE_API_KEY` or `HF_TOKEN` is missing, prints the configuration it is
using (never the key), and `exec`s the existing entrypoint:

```bash
exec python serve.py --host 0.0.0.0 --port "$PORT"
```

To run it detached with an auditable log:

```bash
cd services/inference
nohup bash run_lightning.sh > natlas-service.log 2>&1 &
tail -f natlas-service.log      # wait for "Model loaded."
```

Loading an 8B model at 4-bit NF4 on a T4 takes a few minutes on a cold cache.
**Wait for `Model loaded.` before testing.**

## 4. Lightning platform settings

Three things decide whether this survives judging. Confirm each in the
Lightning UI — control names move between releases:

1. **Expose port `8000` publicly over HTTPS.** Lightning gives the studio a
   stable hostname; note it exactly, with no trailing slash.
2. **Disable idle shutdown / auto-sleep.** A studio that sleeps takes the
   endpoint down and, on wake, pays the full model-load cost again. This is the
   single most likely cause of a dead demo.
3. **Persistent storage for `HF_HOME`** (see the table above), so a restart
   does not re-download the weights.

## 5. Confirm it before claiming anything

Run these from your laptop against the Lightning hostname. **The endpoint is
not operational until all three pass.**

```bash
BASE="https://<your-lightning-host>"
KEY="<your INFERENCE_API_KEY>"

# a) liveness and load state — NOT proof of inference
curl -sS "$BASE/health"

# b) auth is actually enforced: this MUST return 401
curl -sS -o /dev/null -w "%{http_code}\n" "$BASE/v1/models"

# c) authenticated model discovery
curl -sS -H "Authorization: Bearer $KEY" "$BASE/v1/models"

# d) a real generation
curl -sS -X POST "$BASE/v1/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"NCAIR1/N-ATLaS","messages":[{"role":"user","content":"Sannu! Menene babban birnin Najeriya?"}],"language":"ha","max_tokens":64}'
```

Expect `/health` to report `"model_loaded": true`, step (b) to be exactly
`401`, and (d) to return real `content`, a `latency_ms` and a `usage` block.
**Save (d)'s output with its timestamp** — that is integration evidence.

## 6. Point Prism at it

Two values on the Prism API, and **both** must change together:

```bash
fly secrets set --app atlas-prism-api \
  NATLAS_BASE_URL='https://<your-lightning-host>' \
  NATLAS_ALLOWED_HOSTS='<your-lightning-host>' \
  NATLAS_API_KEY='<the key>'
```

`NATLAS_ALLOWED_HOSTS` is the SSRF allowlist. If the host is missing from it
Prism refuses the call — that is the guard working, not a bug. The hostname is
bare there (no scheme, no trailing slash).

Then the claim that counts, through Prism itself:

```bash
POST /api/v1/connections/{id}/verify   ->   "verified": true
```

A loaded model and a green `/health` are not an integration. Only a
`verified: true` from Prism is.

## 7. Security posture, for the record

What the service does enforce:

- Bearer auth on `/v1/models` and `/v1/chat/completions`; identical 401 for a
  missing and a wrong key, so there is no oracle for guessing.
- Refuses to start with no key configured; returns 503 rather than serving open.
- `max_tokens` bounded 1–2048 by schema **and** hard-clamped server-side to
  `MAX_NEW_TOKENS`; `temperature` bounded 0.0–2.0.
- Serves exactly one model id; a request naming another gets 400, never a
  silent substitution.
- A GPU/OOM failure returns 503 — never a fabricated completion.

**Known gap, unfixed:** request *input* size is unbounded — no per-message
`max_length`, no cap on message count, and no tokenizer truncation. A very
large prompt can therefore occupy the GPU for a long time while holding the
generation lock. This mattered less behind a short-lived tunnel; on a
persistent public endpoint it matters more. The fix is small and is recorded in
`PROJECT_STATUS.md`.

---

## 8. Deploying through Lightning's managed Inference feature

Two ways to run this on Lightning. They use the **same** `natlas_inference/`
code; only the launcher differs.

### A. Studio with an exposed port (simplest, what you have now)

```bash
cd services/inference
pip install -e .                    # torch/transformers already present in your studio
nohup bash run_lightning.sh > natlas-service.log 2>&1 &
tail -f natlas-service.log          # wait for "Model loaded."
```

Then expose port `8000` publicly and disable idle shutdown (§4).

### B. Managed Deployment from the container

`Dockerfile` in this directory packages the service unmodified:

```bash
docker build -t natlas-inference services/inference
```

What the deployment needs configured:

| Setting | Value |
|---|---|
| Port | `8000` |
| Health check path | `/health` (allow a long start period — an 8B 4-bit load takes minutes) |
| Secrets | `INFERENCE_API_KEY`, `HF_TOKEN` |
| Persistent volume | mounted at `/cache` (this is `HF_HOME`) |
| GPU | one T4 or better; ~6 GB VRAM at 4-bit NF4 |
| Replicas | **1** — generation is serialised by design; a second replica doubles VRAM for no throughput gain |
| Scale to zero | **off** — a cold start re-loads an 8B model |

The model is deliberately **not** baked into the image: it downloads at startup
with `HF_TOKEN` and caches in the mounted volume. That keeps the image small,
keeps gated weights out of an artifact registry, and means the image contains
no credential.

### Two honest caveats

1. **The Dockerfile has not been built or run here.** It needs a CUDA GPU and a
   multi-gigabyte torch base image, neither of which exists on this laptop. The
   logic is a straight packaging of the service that is already proven working,
   but **treat it as unverified until a build succeeds** — then record that
   build as evidence.
2. **If Lightning's Inference feature expects a `LitServe` API class rather
   than a container**, say so and a thin adapter can be added that calls the
   same `Engine` and returns the same response shape. That stays a wrapper, not
   a rewrite — Prism's contract must not change, because the recorded evidence
   depends on it.

**Neither path is operational until §5 passes against the public hostname.**
