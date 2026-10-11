"""ATLAS Prism API entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1 import auth, projects, runs, suites
from app.core.config import settings
from app.evaluation.runner import recover_interrupted_runs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("atlas_prism")

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs orphaned by a restart are marked failed, never left 'running'.
    try:
        recovered = recover_interrupted_runs()
        if recovered:
            log.warning("Marked %d interrupted run(s) as failed at startup.", recovered)
    except Exception as exc:  # a cold DB must not stop the app from booting
        log.warning("Could not run interrupted-run recovery: %s: %s", type(exc).__name__, exc)
    yield


app = FastAPI(
    title="ATLAS Prism API",
    version=__version__,
    description=(
        "AI assurance platform for N-ATLAS integrations. Guard (reliability), "
        "Shield (authorized security testing), Pulse (evaluation-time "
        "observability). All metrics derive from persisted inference traces; "
        "no simulated inference is ever presented as real."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth.router, projects.router, suites.router, runs.router):
    app.include_router(r, prefix=API_PREFIX)


@app.get("/health", tags=["meta"])
def health() -> dict:
    """API liveness only.

    This says nothing about N-ATLAS. Model integration is proven only by
    POST /api/v1/connections/{id}/verify making a real authenticated call.
    """
    return {
        "status": "ok",
        "version": __version__,
        "scope": "api process only - not a model integration check",
        "natlas_credentials_configured": settings.natlas_credentials_present,
    }
