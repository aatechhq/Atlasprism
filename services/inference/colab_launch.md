# Running the N-ATLAS inference service on Colab

Copy-paste cells for a T4 runtime. **Runtime → Change runtime type → T4 GPU**
first, then confirm with cell 1.

Nothing here runs on a local laptop: the model is loaded only on the GPU host.

## 1. Confirm the GPU

```python
!nvidia-smi
import torch; print("CUDA:", torch.cuda.is_available(), torch.cuda.get_device_name(0))
```

## 2. Install dependencies

```python
!pip -q install "transformers>=4.44" "accelerate>=0.34" "bitsandbytes>=0.43" \
                "sentencepiece>=0.2" "fastapi>=0.115" "uvicorn[standard]>=0.32"
```

## 3. Authenticate to Hugging Face

Use a token with access to the gated repo. Paste it into the prompt — do not
hard-code it in a cell you might share.

```python
from huggingface_hub import notebook_login
notebook_login()
```

## 4. Get the service code

```python
# Replace with the repository URL once it is pushed.
!git clone <YOUR-REPO-URL> atlas-prism
%cd atlas-prism/services/inference
```

Or upload the `services/inference/` folder directly.

## 5. Set the service key and start it

```python
import os, secrets
os.environ["INFERENCE_API_KEY"] = secrets.token_urlsafe(32)
os.environ["MODEL_ID"] = "NCAIR1/N-ATLaS"
os.environ["LOAD_IN_4BIT"] = "1"
print("Give this key to Prism as NATLAS_API_KEY:")
print(os.environ["INFERENCE_API_KEY"])
```

```python
import subprocess, sys
proc = subprocess.Popen([sys.executable, "serve.py", "--port", "8000"])
```

Loading an 8B model at 4-bit takes a few minutes on a T4. Watch for
`Model loaded.`

## 6. Verify locally inside Colab first

```python
import json, urllib.request, os
key = os.environ["INFERENCE_API_KEY"]

def post(path, body):
    req = urllib.request.Request(
        "http://127.0.0.1:8000" + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    return json.load(urllib.request.urlopen(req, timeout=300))

print(json.load(urllib.request.urlopen("http://127.0.0.1:8000/health")))
print(post("/v1/chat/completions", {
    "model": "NCAIR1/N-ATLaS",
    "messages": [{"role": "user", "content": "Sannu! Menene babban birnin Najeriya?"}],
    "language": "ha",
    "max_tokens": 64,
}))
```

If that returns real generated text, **inference works**. That is the moment
the integration stops being blocked — and the output of this cell, with its
timestamp, is the integration evidence worth saving.

## 7. Expose it with a tunnel

Cloudflare quick tunnel (no account needed):

```python
!wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O cloudflared
!chmod +x cloudflared
import subprocess
tunnel = subprocess.Popen(["./cloudflared", "tunnel", "--url", "http://localhost:8000",
                           "--no-autoupdate"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
# Watch the output for the https://<random>.trycloudflare.com URL.
for line in tunnel.stdout:
    print(line, end="")
    if "trycloudflare.com" in line:
        break
```

## 8. Point Prism at it

On the machine running the Prism API, in `services/api/.env`:

```
NATLAS_BASE_URL=https://<your-tunnel-host>
NATLAS_API_KEY=<the key printed in step 5>
NATLAS_ALLOWED_HOSTS=<your-tunnel-host>
```

`NATLAS_ALLOWED_HOSTS` must contain the tunnel host or Prism refuses to call it
— that allowlist is the SSRF guard, and it is doing its job if it blocks a URL
you forgot to add.

Then restart the Prism API and verify through Prism itself:

```bash
curl -X POST http://localhost:8000/api/v1/connections/<connection-id>/verify \
     -H "Authorization: Bearer <prism-token>"
```

A `"verified": true` response here is the real thing: Prism made an
authenticated generation call against the actual model and recorded the
latency, model id and response excerpt.

## Limitations to keep in mind

- **The tunnel URL is temporary.** It changes on every restart and dies with
  the runtime. Update `NATLAS_BASE_URL` and `NATLAS_ALLOWED_HOSTS` each time.
- **Colab runtimes are reclaimed.** For the judging period, move this service
  to dedicated GPU hosting and use a stable hostname.
- **A quick tunnel is public.** The Bearer key is the only thing protecting a
  GPU endpoint, so use a long random key and rotate it if it is ever shared in
  a screenshot or log.
