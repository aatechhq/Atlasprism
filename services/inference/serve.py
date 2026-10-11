"""Entrypoint: python serve.py [--port 8000]

Reads configuration from the environment (or a .env beside this file, if
python-dotenv happens to be installed). Intended to run on a GPU host.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys


def _load_dotenv_if_present() -> None:
    env_file = pathlib.Path(__file__).with_name(".env")
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve NCAIR1/N-ATLaS over HTTP.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    _load_dotenv_if_present()

    import uvicorn

    from natlas_inference.config import Config

    config = Config.from_env()
    try:
        config.require_api_key()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if not config.hf_token:
        print(
            "WARNING: HF_TOKEN is empty. A gated model will fail to download.",
            file=sys.stderr,
        )

    print(f"Serving {config.model_id} on {args.host}:{args.port} "
          f"(4bit={config.load_in_4bit}, preload={config.preload})")
    uvicorn.run("natlas_inference.app:app", host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
