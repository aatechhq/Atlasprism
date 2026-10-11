"""TEST-ONLY connector.

Importing this in a production code path is a bug. `build()` refuses to run
unless ATLAS_PRISM_ALLOW_FAKE_CONNECTOR=1 is set, which only the test suite
and conftest do. No API route constructs it.
"""
from __future__ import annotations

import os

from app.connectors.base import InferenceResult, Outcome, VerificationResult

ENV_FLAG = "ATLAS_PRISM_ALLOW_FAKE_CONNECTOR"


class FakeConnector:
    """Deterministic scripted connector for unit tests."""

    name = "fake(test-only)"

    def __init__(
        self,
        replies: list[str] | None = None,
        outcome: Outcome = Outcome.OK,
        latency_ms: int = 12,
        error_message: str | None = None,
    ) -> None:
        if os.environ.get(ENV_FLAG) != "1":
            raise RuntimeError(
                "FakeConnector is test-only. Set "
                f"{ENV_FLAG}=1 in tests; never enable it in a deployed process."
            )
        self._replies = list(replies or ["fixture reply"])
        self._outcome = outcome
        self._latency = latency_ms
        self._error = error_message
        self.calls: list[dict] = []

    async def generate(self, messages, *, language="en", timeout_s=None) -> InferenceResult:
        self.calls.append({"messages": messages, "language": language})
        if self._outcome is not Outcome.OK:
            return InferenceResult(
                outcome=self._outcome,
                latency_ms=self._latency,
                error_message=self._error or f"fixture {self._outcome.value}",
                model_id="fixture-model",
            )
        text = self._replies[min(len(self.calls) - 1, len(self._replies) - 1)]
        return InferenceResult(
            outcome=Outcome.OK,
            text=text,
            model_id="fixture-model",
            latency_ms=self._latency,
            upstream_status=200,
            response_metadata={"shape": "fixture", "fixture": True},
        )

    async def verify(self) -> VerificationResult:
        return VerificationResult(
            verified=False,
            state="blocked",
            detail="FakeConnector can never verify a live integration.",
            outcome=Outcome.BLOCKED,
        )
