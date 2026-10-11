# Running the N-ATLAS inference service on Colab

Two paths. **Use path A** if the model is already loaded in your notebook — it
is the normal case once you have confirmed inference, and it neither
re-downloads the weights nor places a second copy on the GPU.

Nothing here runs on a local laptop: the model is loaded only on the GPU host.

---

## Path A — serve a model that is already loaded (recommended)

Preconditions: your notebook already has `model` and `tokenizer` in memory, on
the GPU, and you have confirmed a real generation.

### A1. Get the service code onto the runtime

**The repository is private**, so `git clone` in Colab would need credentials
you should not paste into a notebook. Upload the code instead. Build the
bundle once, locally:

```bash
cd services/inference
python -c "import zipfile,pathlib; z=zipfile.ZipFile('../../natlas-inference.zip','w',zipfile.ZIP_DEFLATED); [z.write(p,p.as_posix()) for p in list(pathlib.Path('.').glob('natlas_inference/*.py'))+[pathlib.Path('serve.py')]]; z.close()"
```

Then in Colab:

```python
from google.colab import files
files.upload()                      # choose natlas-inference.zip
import zipfile, sys
zipfile.ZipFile("natlas-inference.zip").extractall("/content/natlas-svc")
sys.path.insert(0, "/content/natlas-svc")
```

The uploaded code is byte-identical to `services/inference/` in the
repository, which is also the better answer if a judge asks what served the
model. If the repository is public by then, `git clone` works just as well.

The service needs only `fastapi`, `uvicorn` and `pydantic` — if they are
missing:

```python
!pip -q install "fastapi>=0.115" "uvicorn[standard]>=0.32" "pydantic>=2.9"
```

### A2. Generate a key and attach the loaded model

```python
import os, secrets

API_KEY = secrets.token_urlsafe(32)
print("Give this to Prism as NATLAS_API_KEY:\n", API_KEY)

from natlas_inference.app import app, attach_preloaded

# `model` and `tokenizer` are YOUR existing objects. Nothing is re-downloaded.
attach_preloaded(model, tokenizer, model_id="NCAIR1/N-ATLaS", api_key=API_KEY)
```

`attach_preloaded` serves the exact objects you pass, sets `preload=False`, and
refuses to run without an API key.

### A3. Start the server in a background thread

Colab already runs an event loop, so run uvicorn on its own thread rather than
reaching for `nest_asyncio`:

```python
import threading, uvicorn

server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8000,
                                       log_level="info"))
threading.Thread(target=server.run, daemon=True).start()
```

### A4. Confirm it inside Colab before exposing it

```python
import json, urllib.request

def call(path, body=None):
    req = urllib.request.Request(
        "http://127.0.0.1:8000" + path,
        data=json.dumps(body).encode() if body else None,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {API_KEY}"},
    )
    return json.load(urllib.request.urlopen(req, timeout=600))

print(json.load(urllib.request.urlopen("http://127.0.0.1:8000/health")))
print(call("/v1/models"))

out = call("/v1/chat/completions", {
    "model": "NCAIR1/N-ATLaS",
    "messages": [{"role": "user", "content": "Sannu! Menene babban birnin Najeriya?"}],
    "language": "ha",
    "max_tokens": 64,
})
print(out["content"])
print("latency_ms:", out["latency_ms"], "| usage:", out["usage"])
```

**Save this cell's output.** With its timestamp it is the integration evidence
worth keeping: the model id, the real latency, and the generated text.

Then continue at [**Connecting Prism**](#connecting-prism) below.

---

## Path B — let the service load the model itself

Use this on a fresh runtime, or on dedicated GPU hosting where no notebook has
loaded anything yet.

### B1. Confirm the GPU

```python
!nvidia-smi
import torch; print("CUDA:", torch.cuda.is_available(), torch.cuda.get_device_name(0))
```

### B2. Install the GPU dependencies

```python
!pip -q install "transformers>=4.44" "accelerate>=0.34" "bitsandbytes>=0.43" \
                "sentencepiece>=0.2" "fastapi>=0.115" "uvicorn[standard]>=0.32"
```

### B3. Authenticate to Hugging Face

The model is gated, so the token needs access to it. Paste it into the prompt
rather than hard-coding it in a cell you might share.

```python
from huggingface_hub import notebook_login
notebook_login()
```

### B4. Configure and start

```python
import os, secrets
os.environ["INFERENCE_API_KEY"] = secrets.token_urlsafe(32)
os.environ["MODEL_ID"] = "NCAIR1/N-ATLaS"
os.environ["LOAD_IN_4BIT"] = "1"
print("NATLAS_API_KEY for Prism:", os.environ["INFERENCE_API_KEY"])
```

```python
%cd /content/atlas-prism/services/inference
import subprocess, sys
proc = subprocess.Popen([sys.executable, "serve.py", "--port", "8000"])
```

Loading an 8B model at 4-bit NF4 takes a few minutes on a T4 (about 5.3 GB of
VRAM). Wait for `Model loaded.`, then verify with the cell in **A4**.

---

## Expose it with a tunnel

Cloudflare quick tunnel, no account needed:

```python
!wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O cloudflared
!chmod +x cloudflared

import subprocess
tunnel = subprocess.Popen(["./cloudflared", "tunnel", "--url", "http://localhost:8000",
                           "--no-autoupdate"],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
for line in tunnel.stdout:
    print(line, end="")
    if "trycloudflare.com" in line:
        break
```

Note the `https://<random>.trycloudflare.com` hostname it prints.

---

## Connecting Prism

On the machine running the Prism API, edit `services/api/.env`:

```
NATLAS_BASE_URL=https://<your-tunnel-host>
NATLAS_API_KEY=<the key printed above>
NATLAS_ALLOWED_HOSTS=<your-tunnel-host>
NATLAS_TIMEOUT_MS=120000
```

Three things to get right:

- **`NATLAS_ALLOWED_HOSTS` must contain the tunnel host**, or Prism refuses to
  call it. That allowlist is the SSRF guard; it is doing its job if it blocks a
  URL you forgot to add.
- **Raise `NATLAS_TIMEOUT_MS`.** Measured latency on a T4 is around 8 seconds
  per generation, and a long prompt or a cold first call is slower. 120000
  (2 minutes) leaves comfortable headroom.
- **Use `max_concurrency: 1` when launching runs.** The service executes
  generations strictly one at a time (a T4 holding an 8B model at 4-bit has no
  headroom for parallel decoding), so a higher value only queues requests and
  risks client timeouts. A 20-case suite at ~8s per case takes roughly three
  minutes.

Restart the Prism API, then verify **through Prism** — this is the step that
actually proves the integration:

```bash
curl -X POST http://localhost:8000/api/v1/connections/<connection-id>/verify \
     -H "Authorization: Bearer <prism-token>"
```

```json
{
  "verified": true, "state": "verified", "outcome": "ok",
  "model_id": "NCAIR1/N-ATLaS", "latency_ms": 8270, "upstream_status": 200,
  "detail": "Authenticated inference succeeded in 8270ms (HTTP 200, model NCAIR1/N-ATLaS)."
}
```

Until that response comes back `verified: true`, Prism-to-N-ATLAS integration
is **not** complete, however well the model runs inside Colab. A successful
generation in a notebook and a successful generation through Prism are two
different claims, and only the second one is the integration.

---

## Limitations to keep in mind

- **The tunnel URL is temporary.** It changes on every restart and dies with
  the runtime. Update `NATLAS_BASE_URL` and `NATLAS_ALLOWED_HOSTS` each time.
- **Colab runtimes are reclaimed**, including mid-run. For the judging period,
  move the service to dedicated GPU hosting with a stable hostname; that is a
  configuration change in Prism, not a code change.
- **A quick tunnel is public.** The Bearer key is the only thing protecting a
  GPU endpoint, so use a long random key and rotate it if it ever appears in a
  screenshot, a log or a shared notebook.
- **If the runtime dies mid-run**, Prism records those cases as `error` with an
  honest outcome (`timeout` or `network`) rather than as test failures, and the
  run ends `partially_completed` or `failed`.
