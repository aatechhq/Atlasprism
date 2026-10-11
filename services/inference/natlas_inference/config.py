"""Service configuration, read from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    api_key: str
    hf_token: str
    model_id: str
    load_in_4bit: bool
    max_new_tokens: int
    allow_cpu: bool
    preload: bool

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            api_key=os.environ.get("INFERENCE_API_KEY", "").strip(),
            hf_token=os.environ.get("HF_TOKEN", "").strip(),
            model_id=os.environ.get("MODEL_ID", "NCAIR1/N-ATLaS").strip(),
            load_in_4bit=_flag("LOAD_IN_4BIT", "1"),
            max_new_tokens=int(os.environ.get("MAX_NEW_TOKENS", "256")),
            allow_cpu=_flag("ALLOW_CPU", "0"),
            preload=_flag("PRELOAD", "1"),
        )

    def require_api_key(self) -> None:
        if not self.api_key:
            raise RuntimeError(
                "INFERENCE_API_KEY is not set. Refusing to start an unauthenticated "
                "inference service - it would be an open proxy to a GPU."
            )
