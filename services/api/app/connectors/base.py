"""Connector interface and normalized result types.

Every inference attempt returns an `InferenceResult` carrying an `Outcome`.
The distinction the whole product rests on:

  * `Outcome.OK`          - the model answered; the result can be scored.
  * anything else         - no valid scoring result exists. This is an ERROR,
                            never a failed test and never a passed defense.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Protocol


class Outcome(str, enum.Enum):
    OK = "ok"
    AUTH = "auth"                  # 401/403 - missing or rejected credential
    RATE_LIMIT = "rate_limit"      # 429
    TIMEOUT = "timeout"            # no response within the client timeout
    NETWORK = "network"            # DNS/TLS/connection failure
    UPSTREAM_ERROR = "upstream_error"  # 5xx or other non-2xx
    SCHEMA = "schema"              # 2xx whose body does not match the contract
    EMPTY = "empty"                # 2xx, valid shape, but no text content
    NOT_FOUND = "not_found"        # 404 - endpoint path wrong
    BAD_REQUEST = "bad_request"    # 400 - e.g. unsupported language
    BLOCKED = "blocked"            # refused before any call was made

    @property
    def is_ok(self) -> bool:
        return self is Outcome.OK

    @property
    def is_scorable(self) -> bool:
        """Only an OK outcome may be handed to a scorer."""
        return self is Outcome.OK


@dataclass(slots=True)
class InferenceResult:
    outcome: Outcome
    text: str | None = None
    model_id: str | None = None
    latency_ms: int | None = None
    upstream_status: int | None = None
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    request_id: str | None = None
    error_message: str | None = None
    request_metadata: dict[str, Any] = field(default_factory=dict)
    response_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.outcome.is_ok


@dataclass(slots=True)
class VerificationResult:
    """Result of a real authenticated inference call.

    `verified` is True only when an actual generation succeeded. A reachable
    /health endpoint does NOT set it (build path 2: "Not acceptable: health
    check or local mock labeled live verified").
    """

    verified: bool
    state: str  # verified | failed | blocked
    detail: str
    outcome: Outcome
    model_id: str | None = None
    latency_ms: int | None = None
    upstream_status: int | None = None
    response_excerpt: str | None = None


class ModelConnector(Protocol):
    name: str

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        language: str = "en",
        timeout_s: float | None = None,
    ) -> InferenceResult: ...

    async def verify(self) -> VerificationResult: ...
