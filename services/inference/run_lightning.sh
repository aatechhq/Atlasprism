#!/usr/bin/env bash
# Start the N-ATLAS inference service for a PERSISTENT deployment.
#
#   bash run_lightning.sh
#
# Deliberately thin: it sets no policy of its own. Everything about how the
# model is loaded and how requests are authenticated lives in
# natlas_inference/, UNCHANGED, so there is one implementation to audit.
#
# Its one job beyond launching is to make a failed start SELF-DESCRIBING. A
# managed deployment that shows "setup activity but no confirmed execution"
# is almost always one of the preflight checks below failing silently.
set -uo pipefail

cd "$(dirname "$0")"

say() { echo "[preflight] $*"; }
fail() { echo "[preflight] FATAL: $*" >&2; exit 2; }

echo "=============================================================="
echo "N-ATLAS inference service -- preflight $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=============================================================="
say "pwd            : $(pwd)"
say "python         : $(command -v python || echo MISSING) ($(python -V 2>&1))"

# --- 1. Credentials. The service refuses to be an open proxy to a GPU. ------
# Presence only is logged, never a value.
if [ -n "${INFERENCE_API_KEY:-}" ]; then
  say "INFERENCE_API_KEY: present (${#INFERENCE_API_KEY} chars)"
else
  fail "INFERENCE_API_KEY is NOT set. serve.py exits 2 before uvicorn starts, so the replica never serves and the platform will delete and recreate it forever. Studio environment variables are NOT inherited by a managed deployment -- set this as a DEPLOYMENT secret."
fi
if [ -n "${HF_TOKEN:-}" ]; then
  say "HF_TOKEN       : present (${#HF_TOKEN} chars)"
else
  say "HF_TOKEN       : ABSENT -- a gated model cannot download. Continuing; /health will report model_loaded:false."
fi

# --- 2. Is the service actually importable here? ----------------------------
if python -c "import natlas_inference, sys; sys.stdout.write(natlas_inference.__file__)" >/tmp/ni_path 2>/tmp/ni_err; then
  say "natlas_inference: $(cat /tmp/ni_path)"
else
  fail "cannot import natlas_inference from $(pwd): $(head -c 300 /tmp/ni_err). Run 'pip install -e .' in the deployment environment, or set the working directory to the folder containing natlas_inference/."
fi

# --- 3. GPU visibility (reported, not enforced) -----------------------------
# A preload failure is CAUGHT by the app, which still serves /health honestly.
# So this is diagnostic: it explains a model_loaded:false, it is not fatal.
python - <<'PY' 2>/dev/null || say "torch         : not importable (model load will fail; /health will say so)"
try:
    import torch
    print(f"[preflight] torch          : {torch.__version__} cuda_available={torch.cuda.is_available()}")
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        print(f"[preflight] gpu            : {p.name} {p.total_memory // (1024**3)} GiB")
    else:
        print("[preflight] gpu            : NONE VISIBLE -- 4-bit NF4 needs ~6 GiB of VRAM")
except Exception as exc:
    print(f"[preflight] torch          : error {type(exc).__name__}: {exc}")
PY

# --- 4. Model cache must persist, or every replica re-downloads ~16 GB ------
export HF_HOME="${HF_HOME:-$PWD/.hf-cache}"
mkdir -p "$HF_HOME" 2>/dev/null || true
if [ -w "$HF_HOME" ]; then
  say "HF_HOME        : $HF_HOME (writable)"
else
  fail "HF_HOME '$HF_HOME' is not writable. Mount a persistent volume there, or the weights re-download on every replica and the readiness probe will never pass."
fi

# --- 5. Model + serving configuration ---------------------------------------
export MODEL_ID="${MODEL_ID:-NCAIR1/N-ATLaS}"
export LOAD_IN_4BIT="${LOAD_IN_4BIT:-1}"
export MAX_NEW_TOKENS="${MAX_NEW_TOKENS:-256}"
export ALLOW_CPU="${ALLOW_CPU:-0}"
export PRELOAD="${PRELOAD:-1}"

PORT="${PORT:-8000}"

# The health-probe trap, stated explicitly because it is the usual killer.
if [ "$PRELOAD" = "1" ]; then
  say "PRELOAD=1      : the model loads BEFORE uvicorn serves, so /health is"
  say "                 UNREACHABLE for several minutes (longer on a cold"
  say "                 cache). The deployment's startup grace MUST exceed"
  say "                 that, or the replica is killed mid-load. Use"
  say "                 PRELOAD=0 if the platform caps the grace period."
else
  say "PRELOAD=0      : uvicorn serves immediately and /health answers at once"
  say "                 with model_loaded:false; the model loads on the FIRST"
  say "                 inference request. Send one warm-up request with a"
  say "                 long timeout before pointing Prism at this host."
fi

say "model          : $MODEL_ID (4bit=$LOAD_IN_4BIT, max_new_tokens=$MAX_NEW_TOKENS)"
say "bind           : 0.0.0.0:$PORT"
say "auth           : Bearer required on /v1/* (key never logged)"
echo "=============================================================="

# exec so signals reach uvicorn directly and the process table stays honest.
exec python serve.py --host 0.0.0.0 --port "$PORT"
