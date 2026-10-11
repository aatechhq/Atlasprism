#!/usr/bin/env bash
# Start the N-ATLAS inference service for a PERSISTENT deployment.
#
#   bash run_lightning.sh
#
# Deliberately thin: it sets no policy of its own, it only fails fast on a
# missing credential and hands control to serve.py. Everything about how the
# model is loaded and how requests are authenticated lives in
# natlas_inference/, unchanged, so there is one implementation to audit.
set -euo pipefail

cd "$(dirname "$0")"

# --- Preconditions, checked loudly ------------------------------------------
: "${INFERENCE_API_KEY:?INFERENCE_API_KEY is not set. Refusing to start an unauthenticated GPU endpoint.}"
: "${HF_TOKEN:?HF_TOKEN is not set. NCAIR1/N-ATLaS is gated and will not download.}"

# --- Model + serving configuration -----------------------------------------
export MODEL_ID="${MODEL_ID:-NCAIR1/N-ATLaS}"
export LOAD_IN_4BIT="${LOAD_IN_4BIT:-1}"   # NF4 + double quant, bfloat16 compute (~6 GB on a T4)
export PRELOAD="${PRELOAD:-1}"             # load ONCE at startup, keep resident in GPU memory
export MAX_NEW_TOKENS="${MAX_NEW_TOKENS:-256}"
export ALLOW_CPU="${ALLOW_CPU:-0}"         # refuse to start without CUDA

# Keep the Hugging Face cache on persistent storage, or an 8B model is
# re-downloaded on every restart. Point HF_HOME at a path that survives.
export HF_HOME="${HF_HOME:-$PWD/.hf-cache}"

PORT="${PORT:-8000}"

echo "--------------------------------------------------------------"
echo "N-ATLAS inference service"
echo "  model        : $MODEL_ID"
echo "  quantization : 4bit=$LOAD_IN_4BIT"
echo "  preload      : $PRELOAD (model stays in GPU memory)"
echo "  max_new_tokens cap: $MAX_NEW_TOKENS"
echo "  HF_HOME      : $HF_HOME"
echo "  bind         : 0.0.0.0:$PORT"
echo "  auth         : Bearer required on /v1/* (key NOT printed)"
echo "  started at   : $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "--------------------------------------------------------------"

# exec so signals reach uvicorn directly and the process table stays honest.
exec python serve.py --host 0.0.0.0 --port "$PORT"
