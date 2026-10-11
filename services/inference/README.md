# N-ATLAS inference service

A small, self-contained FastAPI service that serves the official
[`NCAIR1/N-ATLaS`](https://huggingface.co/NCAIR1/N-ATLaS) model over an
OpenAI-shaped HTTP API, so ATLAS Prism can evaluate it through one stable
contract.

It is **deliberately a separate service with its own dependencies.** Hugging
Face authentication, PyTorch, BitsAndBytes and model loading live here and
nowhere near the Prism backend — Prism talks to this over HTTP and knows
nothing about transformers.

> **Do not run this on a laptop.** It loads an 8B-parameter model and needs a
> CUDA GPU (~6 GB VRAM at 4-bit NF4). On a machine without CUDA it refuses to
> start unless `ALLOW_CPU=1` is set explicitly, which is slow and intended only
> for a smoke test on a small substitute model.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/health` | no | Liveness + whether the model is loaded. Never proof of inference. |
| `GET` | `/v1/models` | yes | The model id this service serves. |
| `POST` | `/v1/chat/completions` | yes | Generation. |

Auth is `Authorization: Bearer $INFERENCE_API_KEY` on the two `/v1` routes.

### `POST /v1/chat/completions`

```json
{
  "model": "NCAIR1/N-ATLaS",
  "messages": [{"role": "user", "content": "Sannu!"}],
  "language": "ha",
  "max_tokens": 256,
  "temperature": 0.7
}
```

Response (the flat shape Prism's connector expects, with an OpenAI-compatible
`choices` array alongside it so standard clients also work):

```json
{
  "content": "Sannu da zuwa!",
  "role": "assistant",
  "finishReason": "stop",
  "model": "NCAIR1/N-ATLaS",
  "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
  "choices": [{"index": 0, "message": {"role": "assistant", "content": "Sannu da zuwa!"},
               "finish_reason": "stop"}]
}
```

## Environment

| Variable | Required | Meaning |
|---|---|---|
| `INFERENCE_API_KEY` | **yes** | Bearer key clients must present. The service refuses to start without one. |
| `HF_TOKEN` | yes, for a gated model | Hugging Face token with access to `NCAIR1/N-ATLaS`. |
| `MODEL_ID` | no | Default `NCAIR1/N-ATLaS`. |
| `LOAD_IN_4BIT` | no | Default `1` (NF4 + double quantization, bfloat16 compute). |
| `MAX_NEW_TOKENS` | no | Default `256`. Hard cap on any request. |
| `ALLOW_CPU` | no | Default `0`. Set `1` only to smoke-test without a GPU. |
| `PRELOAD` | no | Default `1`: load the model at startup so the first request is not slow. |

Never commit a real token or key. See `.env.example`.

## Running on Colab

See [`colab_launch.md`](colab_launch.md) for the copy-paste cells. Summary:

1. Runtime → Change runtime type → **T4 GPU**.
2. Install dependencies, log in to Hugging Face, start this service.
3. Open a tunnel (Cloudflare quick tunnel or ngrok) to get a public HTTPS URL.
4. Give Prism that URL as `NATLAS_BASE_URL` and the same key as
   `NATLAS_API_KEY`, then call Prism's
   `POST /api/v1/connections/{id}/verify`.

**A Colab tunnel URL is temporary.** It dies with the runtime, and the URL
changes every restart. That is why Prism takes the base URL from an environment
variable and keeps a host allowlist: moving to dedicated GPU hosting for the
judging period is a config change, not a code change.

## Local tests

The request/response contract is tested without downloading any model — the
model layer is injected, so the HTTP surface, auth and error handling are
covered on a laptop:

```bash
cd services/inference
uv venv .venv && uv pip install --python .venv -e ".[dev]"
.venv/bin/python -m pytest -q      # Windows: .venv/Scripts/python.exe
```
