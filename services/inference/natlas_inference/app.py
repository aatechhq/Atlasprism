"""HTTP surface: /health, /v1/models, /v1/chat/completions."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from dataclasses import replace

from natlas_inference import __version__
from natlas_inference.config import Config
from natlas_inference.engine import Engine, PreloadedEngine, TransformersEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("natlas_inference")

CONFIG: Config = Config.from_env()
ENGINE: Engine | None = None
bearer = HTTPBearer(auto_error=False)

# One generation at a time. A Tesla T4 holding an 8B model at 4-bit has no
# headroom for concurrent decoding: parallel requests would contend for VRAM
# and could OOM mid-run. Requests queue here instead, which is slower but
# never fails for a reason the caller cannot see.
GENERATION_LOCK = asyncio.Lock()


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)
    model: str | None = None
    language: str | None = Field(default=None, max_length=10)
    max_tokens: int | None = Field(default=None, ge=1, le=2048)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


def set_engine(engine: Engine | None) -> None:
    """Injection point: tests pass a stub, the GPU host passes a real engine."""
    global ENGINE
    ENGINE = engine


def attach_preloaded(model, tokenizer, model_id: str | None = None,
                     api_key: str | None = None) -> None:
    """Serve a model that is ALREADY loaded in this process.

    The Colab path. Call this from the notebook after the model is on the GPU:

        from natlas_inference.app import app, attach_preloaded
        attach_preloaded(model, tokenizer, api_key=MY_KEY)

    Nothing is re-downloaded and no second copy is placed on the GPU.
    """
    global CONFIG
    resolved_id = model_id or CONFIG.model_id
    if api_key:
        CONFIG = replace(CONFIG, api_key=api_key, model_id=resolved_id, preload=False)
    else:
        CONFIG = replace(CONFIG, model_id=resolved_id, preload=False)
    CONFIG.require_api_key()
    set_engine(PreloadedEngine(model, tokenizer, model_id=resolved_id))
    log.info("Attached preloaded model %s (no reload).", resolved_id)


def set_config(config: Config) -> None:
    global CONFIG
    CONFIG = config


def require_auth(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)] = None,
) -> None:
    if not CONFIG.api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "Service has no INFERENCE_API_KEY configured."},
        )
    if creds is None or creds.credentials != CONFIG.api_key:
        # Same response for missing and wrong: no oracle for key guessing.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Missing or incorrect Bearer key."},
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    CONFIG.require_api_key()
    global ENGINE
    if ENGINE is None:
        ENGINE = TransformersEngine(
            CONFIG.model_id, hf_token=CONFIG.hf_token,
            load_in_4bit=CONFIG.load_in_4bit, allow_cpu=CONFIG.allow_cpu,
        )
    if CONFIG.preload:
        log.info("Preloading %s (4bit=%s)...", CONFIG.model_id, CONFIG.load_in_4bit)
        try:
            ENGINE.load()
            log.info("Model loaded.")
        except Exception as exc:
            # Start anyway so /health can report the failure honestly.
            log.error("Model preload failed: %s: %s", type(exc).__name__, exc)
    yield


app = FastAPI(
    title="N-ATLAS Inference Service",
    version=__version__,
    description=(
        "Minimal authenticated inference service for NCAIR1/N-ATLaS. Serves the "
        "real model on GPU hardware; it never returns a canned or simulated "
        "completion."
    ),
    lifespan=lifespan,
)


@app.get("/health", tags=["meta"])
def health() -> dict[str, Any]:
    """Liveness and load state. NOT proof that inference works."""
    return {
        "status": "ok",
        "version": __version__,
        "model_id": CONFIG.model_id,
        "model_loaded": bool(ENGINE and ENGINE.loaded),
        "quantization": "nf4-4bit" if CONFIG.load_in_4bit else "none",
        "busy": GENERATION_LOCK.locked(),
        "execution": "sequential (one generation at a time)",
        "note": (
            "Liveness only. A loaded model is not evidence of a successful "
            "generation - call POST /v1/chat/completions."
        ),
    }


@app.get("/v1/models", tags=["models"], dependencies=[Depends(require_auth)])
def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [{
            "id": CONFIG.model_id,
            "object": "model",
            "owned_by": "NCAIR1",
            "loaded": bool(ENGINE and ENGINE.loaded),
        }],
    }


@app.post("/v1/chat/completions", tags=["inference"], dependencies=[Depends(require_auth)])
async def chat_completions(body: ChatRequest) -> dict[str, Any]:
    if ENGINE is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "No inference engine configured."},
        )
    if body.model and body.model != CONFIG.model_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"This service serves {CONFIG.model_id!r}, not {body.model!r}.",
                "served_model": CONFIG.model_id,
            },
        )

    max_new = min(body.max_tokens or CONFIG.max_new_tokens, CONFIG.max_new_tokens)
    engine = ENGINE
    try:
        # Serialize generations, and run each in a worker thread so /health
        # stays responsive while the GPU is busy.
        async with GENERATION_LOCK:
            gen = await asyncio.to_thread(
                engine.generate,
                [m.model_dump() for m in body.messages],
                max_new_tokens=max_new,
                temperature=body.temperature,
                language=body.language,
            )
    except RuntimeError as exc:
        # e.g. no GPU, or OOM. Reported as an upstream failure, never as a completion.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": f"Generation unavailable: {exc}"},
        )

    usage = {
        "prompt_tokens": gen.prompt_tokens,
        "completion_tokens": gen.completion_tokens,
        "total_tokens": gen.prompt_tokens + gen.completion_tokens,
    }
    return {
        # Flat shape, as the N-ATLAS quickstart documents it.
        "content": gen.text,
        "role": "assistant",
        "finishReason": gen.finish_reason,
        "model": CONFIG.model_id,
        "usage": usage,
        "latency_ms": gen.latency_ms,
        # OpenAI-compatible mirror so standard clients work unchanged.
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": gen.text},
            "finish_reason": gen.finish_reason,
        }],
    }
