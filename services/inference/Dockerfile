# N-ATLAS inference service -- GPU container for a managed inference platform
# (Lightning AI Deployments/Inference, or any container host with a CUDA GPU).
#
#   docker build -t natlas-inference services/inference
#
# This image only PACKAGES the existing service. It changes no behaviour:
# natlas_inference/ is copied in unmodified, and the container runs the same
# serve.py entrypoint used on Colab and in a Lightning Studio. One
# implementation, three ways of launching it.
#
# The model is NOT baked into the image. It is downloaded at startup using
# HF_TOKEN and cached in HF_HOME, which must be a mounted persistent volume or
# an 8B model is re-fetched on every cold start.
FROM pytorch/pytorch:2.4.0-cuda12.1-cudnn9-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# curl for the healthcheck only.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Dependencies first so a code change does not re-resolve the GPU stack.
COPY pyproject.toml /srv/pyproject.toml
COPY natlas_inference/__init__.py /srv/natlas_inference/__init__.py
RUN pip install --no-cache-dir ".[gpu]"

# The service itself, unmodified.
COPY natlas_inference/ /srv/natlas_inference/
COPY serve.py /srv/serve.py

# Defaults matching the documented deployment. INFERENCE_API_KEY and HF_TOKEN
# are deliberately absent: they are injected at run time as secrets, and the
# service refuses to start without a key rather than serving open.
ENV MODEL_ID=NCAIR1/N-ATLaS \
    LOAD_IN_4BIT=1 \
    PRELOAD=1 \
    MAX_NEW_TOKENS=256 \
    ALLOW_CPU=0 \
    HF_HOME=/cache/huggingface \
    PORT=8000

# Mount a persistent volume here, or the weights download every cold start.
VOLUME ["/cache"]

EXPOSE 8000

# Liveness and load state only -- deliberately NOT proof that inference works.
# start-period is long because an 8B model at 4-bit NF4 takes minutes to load.
HEALTHCHECK --interval=30s --timeout=10s --start-period=600s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" > /dev/null || exit 1

CMD ["sh", "-c", "exec python serve.py --host 0.0.0.0 --port ${PORT:-8000}"]
