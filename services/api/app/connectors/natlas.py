"""N-ATLAS gateway connector.

Contract, confirmed against https://natlas-docs.vercel.app/quickstart
(read 2026-10-11):

    POST {base}/v1/chat/completions
    Authorization: Bearer <NATLAS_API_KEY>
    Content-Type: application/json
    {"model": "NCAIR1/N-ATLaS",
     "messages": [{"role": "user", "content": "Sannu!"}],
     "language": "ha"}

The documented success body is flat (`content`, `role`, `finishReason`,
`model`, `usage`). Standard OpenAI responses instead nest the text under
`choices[0].message.content`. The gateway is described as "OpenAI-shaped", and
we have not yet been able to observe a live response, so `_extract_text`
accepts BOTH and records which shape was seen. That is deliberate tolerance at
the parse boundary, not a guess about which one is real.

Documented errors: 401 missing/incorrect Bearer key, 400 unsupported language
or decode failure. Default client timeout 60s (NATLAS_TIMEOUT_MS).
"""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.connectors.base import InferenceResult, Outcome, VerificationResult
from app.core.config import settings

CHAT_PATH = "/v1/chat/completions"
_EXCERPT_LIMIT = 280


class NatlasConnector:
    """The one real inference adapter (PRD 3: exactly one, auditable)."""

    name = "natlas"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model_id: str | None = None,
        timeout_s: float | None = None,
        allowed_hosts: set[str] | None = None,
    ) -> None:
        # None means "use the configured default"; "" means "explicitly unset",
        # which must stay unset so a misconfiguration is reported, not masked.
        resolved = settings.natlas_base_url if base_url is None else base_url
        self.base_url = (resolved or "").rstrip("/")
        self._api_key = api_key if api_key is not None else settings.natlas_api_key
        self.model_id = model_id or settings.natlas_model_id
        self.timeout_s = timeout_s or settings.natlas_timeout_seconds
        self.allowed_hosts = (
            allowed_hosts if allowed_hosts is not None else settings.allowed_inference_hosts
        )

    # --- guards ------------------------------------------------------------

    def _blocked_reason(self) -> str | None:
        """Why no call may be attempted. None means we may proceed."""
        if not self.base_url:
            return "No N-ATLAS base URL configured (set NATLAS_BASE_URL)."
        host = (urlparse(self.base_url).hostname or "").lower()
        if not host:
            return f"Base URL is not a valid absolute URL: {self.base_url!r}"
        if self.allowed_hosts and host not in self.allowed_hosts:
            # SSRF guard: never call a host the operator has not allowlisted.
            return (
                f"Host {host!r} is not in NATLAS_ALLOWED_HOSTS. Refusing to send "
                "inference to a non-allowlisted host."
            )
        if not str(self._api_key or "").strip():
            return (
                "No N-ATLAS API key configured (NATLAS_API_KEY is empty). "
                "Live inference is BLOCKED - not failed, and not simulated."
            )
        return None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    # --- parsing -----------------------------------------------------------

    @staticmethod
    def _extract_text(body: Any) -> tuple[str | None, str]:
        """Return (text, shape_seen). Accepts the flat and nested shapes."""
        if not isinstance(body, dict):
            return None, "not-an-object"
        content = body.get("content")
        if isinstance(content, str):
            return content, "flat"
        choices = body.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message")
                if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                    return msg["content"], "openai-nested"
                if isinstance(first.get("text"), str):
                    return first["text"], "openai-text"
        for key in ("output_text", "response", "text"):
            if isinstance(body.get(key), str):
                return body[key], f"alt:{key}"
        return None, "unrecognised"

    # --- inference ---------------------------------------------------------

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        language: str = "en",
        timeout_s: float | None = None,
    ) -> InferenceResult:
        blocked = self._blocked_reason()
        request_metadata = {
            "endpoint": f"{self.base_url}{CHAT_PATH}" if self.base_url else None,
            "model": self.model_id,
            "language": language,
            "message_count": len(messages),
            "auth": "bearer <redacted>",
        }
        if blocked:
            return InferenceResult(
                outcome=Outcome.BLOCKED,
                error_message=blocked,
                model_id=self.model_id,
                request_metadata=request_metadata,
            )

        payload = {"model": self.model_id, "messages": messages, "language": language}
        url = f"{self.base_url}{CHAT_PATH}"
        effective_timeout = timeout_s or self.timeout_s
        started = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=effective_timeout) as client:
                resp = await client.post(url, json=payload, headers=self._headers())
        except httpx.TimeoutException as exc:
            return InferenceResult(
                outcome=Outcome.TIMEOUT,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error_message=f"No response within {effective_timeout:.0f}s: {type(exc).__name__}",
                model_id=self.model_id,
                request_metadata=request_metadata,
            )
        except httpx.HTTPError as exc:
            return InferenceResult(
                outcome=Outcome.NETWORK,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error_message=f"{type(exc).__name__}: {exc}",
                model_id=self.model_id,
                request_metadata=request_metadata,
            )

        latency_ms = int((time.perf_counter() - started) * 1000)
        status = resp.status_code
        request_id = resp.headers.get("x-request-id") or resp.headers.get("x-amzn-requestid")
        base = {
            "latency_ms": latency_ms,
            "upstream_status": status,
            "request_id": request_id,
            "model_id": self.model_id,
            "request_metadata": request_metadata,
        }

        if status in (401, 403):
            return InferenceResult(
                outcome=Outcome.AUTH,
                error_message=f"Gateway rejected the credential (HTTP {status}).",
                **base,
            )
        if status == 404:
            return InferenceResult(
                outcome=Outcome.NOT_FOUND,
                error_message=f"HTTP 404 for {CHAT_PATH} - endpoint path may be wrong.",
                **base,
            )
        if status == 400:
            return InferenceResult(
                outcome=Outcome.BAD_REQUEST,
                error_message=f"HTTP 400 - rejected request (unsupported language?): {resp.text[:200]}",
                **base,
            )
        if status == 429:
            return InferenceResult(
                outcome=Outcome.RATE_LIMIT,
                error_message="HTTP 429 - rate limited by gateway.",
                **base,
            )
        if status >= 500:
            return InferenceResult(
                outcome=Outcome.UPSTREAM_ERROR,
                error_message=f"HTTP {status} from gateway: {resp.text[:200]}",
                **base,
            )
        if status >= 300:
            return InferenceResult(
                outcome=Outcome.UPSTREAM_ERROR,
                error_message=f"Unexpected HTTP {status}: {resp.text[:200]}",
                **base,
            )

        try:
            body = resp.json()
        except ValueError:
            return InferenceResult(
                outcome=Outcome.SCHEMA,
                error_message="Gateway returned 2xx with a non-JSON body.",
                response_metadata={"body_excerpt": resp.text[:_EXCERPT_LIMIT]},
                **base,
            )

        text, shape = self._extract_text(body)
        reported_model = body.get("model") if isinstance(body, dict) else None
        usage = body.get("usage") if isinstance(body, dict) else None
        finish = body.get("finishReason") or body.get("finish_reason") if isinstance(body, dict) else None
        response_metadata = {
            "shape": shape,
            "reported_model": reported_model,
            "keys": sorted(body)[:20] if isinstance(body, dict) else None,
        }

        if text is None:
            return InferenceResult(
                outcome=Outcome.SCHEMA,
                error_message=(
                    f"2xx body did not match the documented contract (shape={shape}); "
                    "no text content found."
                ),
                response_metadata=response_metadata,
                usage=usage if isinstance(usage, dict) else None,
                **base,
            )
        if not text.strip():
            return InferenceResult(
                outcome=Outcome.EMPTY,
                text=text,
                error_message="Gateway returned an empty completion.",
                response_metadata=response_metadata,
                usage=usage if isinstance(usage, dict) else None,
                **base,
            )

        if reported_model and self.model_id and reported_model != self.model_id:
            # Recorded, not fatal: evidence must show which model actually answered.
            response_metadata["model_mismatch"] = {
                "requested": self.model_id,
                "reported": reported_model,
            }

        return InferenceResult(
            outcome=Outcome.OK,
            text=text,
            finish_reason=finish if isinstance(finish, str) else None,
            usage=usage if isinstance(usage, dict) else None,
            response_metadata=response_metadata,
            **{**base, "model_id": reported_model or self.model_id},
        )

    # --- verification ------------------------------------------------------

    async def verify(self) -> VerificationResult:
        """Exercise a real authenticated inference call. Health checks do not count."""
        result = await self.generate(
            [{"role": "user", "content": "Reply with the single word: ready"}],
            language="en",
            timeout_s=min(self.timeout_s, 90.0),
        )
        if result.ok:
            excerpt = (result.text or "")[:_EXCERPT_LIMIT]
            return VerificationResult(
                verified=True,
                state="verified",
                detail=(
                    f"Authenticated inference succeeded in {result.latency_ms}ms "
                    f"(HTTP {result.upstream_status}, model {result.model_id})."
                ),
                outcome=result.outcome,
                model_id=result.model_id,
                latency_ms=result.latency_ms,
                upstream_status=result.upstream_status,
                response_excerpt=excerpt,
            )
        state = "blocked" if result.outcome is Outcome.BLOCKED else "failed"
        return VerificationResult(
            verified=False,
            state=state,
            detail=f"{result.outcome.value}: {result.error_message}",
            outcome=result.outcome,
            model_id=result.model_id,
            latency_ms=result.latency_ms,
            upstream_status=result.upstream_status,
        )

    async def health(self) -> dict[str, Any]:
        """Gateway /health. Diagnostic only - NEVER evidence of integration."""
        if not self.base_url:
            return {"reachable": False, "detail": "No base URL configured."}
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout_s, 30.0)) as client:
                resp = await client.get(f"{self.base_url}/health")
            return {
                "reachable": True,
                "status": resp.status_code,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "body_excerpt": resp.text[:200],
                "note": "Reachability only. This is not integration evidence.",
            }
        except httpx.HTTPError as exc:
            return {
                "reachable": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "detail": f"{type(exc).__name__}: {exc}",
                "note": "Reachability only. This is not integration evidence.",
            }
