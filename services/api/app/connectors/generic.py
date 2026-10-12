"""Connector for a developer's own deployed application.

The N-ATLAS connector targets the documented gateway. This one targets an
endpoint the developer runs — their assistant, with their retrieval, their
tools and their guardrails all in the path. That is a strictly better subject
of evaluation than a system prompt replayed against the base model, because it
tests the thing that actually ships.

It speaks the OpenAI-compatible chat-completions shape, which most frameworks
expose, and returns the same normalised `InferenceResult` as every other
connector, so scoring, traces, Pulse and exports need no knowledge of it.

Two safety properties, enforced here rather than trusted to the caller:

* The endpoint passes `netguard` containment on **every** call, not only when
  the connection was created. DNS can change between those two moments.
* Redirects are refused. A redirect could leave the address that containment
  approved.

Authorisation — whether the caller may point adversarial traffic at this host
at all — is enforced before a connection is created, in the route layer, using
`HostVerification`. It is not this module's job and it is not optional.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from app.connectors.base import InferenceResult, Outcome, VerificationResult
from app.core.netguard import EndpointRejected, check_endpoint

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _extract_text(payload: dict[str, Any]) -> str | None:
    """Pull the reply out of either shape we accept.

    The flat `content` field Prism's own inference service returns, or the
    OpenAI-compatible `choices[0].message.content`.
    """
    if isinstance(payload.get("content"), str):
        return payload["content"]
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(msg, dict) and isinstance(msg.get("content"), str):
            return msg["content"]
        if isinstance(choices[0], dict) and isinstance(choices[0].get("text"), str):
            return choices[0]["text"]
    return None


class GenericHttpConnector:
    """Calls a developer-owned, OpenAI-compatible endpoint."""

    def __init__(self, *, base_url: str, model_id: str | None = None,
                 api_key: str | None = None, timeout_ms: int = 120_000,
                 path: str = "/v1/chat/completions") -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.model_id = model_id or "application-under-test"
        self._api_key = api_key
        self._timeout = max(1.0, timeout_ms / 1000)
        self._path = path if path.startswith("/") else f"/{path}"

    # -- internals ---------------------------------------------------------

    def _post(self, body: dict[str, Any]) -> tuple[Outcome, int | None, Any, str | None]:
        url = f"{self.base_url}{self._path}"
        try:
            # Re-checked per call: DNS can change after the connection was made.
            check_endpoint(url)
        except EndpointRejected as exc:
            return Outcome.BLOCKED, None, None, str(exc)

        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "User-Agent": "atlas-prism/1.0"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        opener = urllib.request.build_opener(_NoRedirect)
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     method="POST", headers=headers)
        try:
            with opener.open(req, timeout=self._timeout) as resp:
                raw = resp.read(MAX_RESPONSE_BYTES)
                status = resp.status
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = b""
            try:
                raw = exc.read(MAX_RESPONSE_BYTES)
            except Exception:
                pass
            detail = raw[:400].decode("utf-8", "replace") if raw else ""
            if status in (401, 403):
                return Outcome.AUTH, status, None, f"Endpoint rejected the credential: {detail}"
            if status == 404:
                return Outcome.NOT_FOUND, status, None, f"No endpoint at {self._path}: {detail}"
            if status == 429:
                return Outcome.RATE_LIMIT, status, None, f"Rate limited: {detail}"
            if status == 400:
                return Outcome.BAD_REQUEST, status, None, f"Endpoint rejected the request: {detail}"
            return Outcome.UPSTREAM_ERROR, status, None, f"HTTP {status}: {detail}"
        except TimeoutError:
            return Outcome.TIMEOUT, None, None, f"No response within {self._timeout:.0f}s."
        except urllib.error.URLError as exc:
            reason = str(getattr(exc, "reason", exc))
            if "timed out" in reason.lower():
                return Outcome.TIMEOUT, None, None, f"No response within {self._timeout:.0f}s."
            return Outcome.NETWORK, None, None, f"Could not reach the endpoint: {reason}"

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return (Outcome.SCHEMA, status, None,
                    "The endpoint returned a 2xx response that is not JSON.")
        if not isinstance(payload, dict):
            return Outcome.SCHEMA, status, None, "Response JSON is not an object."
        return Outcome.OK, status, payload, None

    # -- connector interface ----------------------------------------------

    async def generate(self, messages: list[dict[str, str]], *, language: str = "en",
                       timeout_s: float | None = None, max_tokens: int | None = None,
                       temperature: float = 0.7) -> InferenceResult:
        body: dict[str, Any] = {"model": self.model_id, "messages": messages,
                                "temperature": temperature}
        if max_tokens:
            body["max_tokens"] = max_tokens
        if language:
            body["language"] = language

        if timeout_s:
            self._timeout = max(1.0, float(timeout_s))
        started = time.perf_counter()
        outcome, status, payload, error = self._post(body)
        latency = int((time.perf_counter() - started) * 1000)

        if outcome is not Outcome.OK:
            return InferenceResult(outcome=outcome, upstream_status=status,
                                   latency_ms=latency, error_message=error,
                                   request_metadata={"endpoint": self.base_url,
                                                     "path": self._path})

        text = _extract_text(payload)
        if text is None:
            return InferenceResult(
                outcome=Outcome.SCHEMA, upstream_status=status, latency_ms=latency,
                error_message=("The response did not contain a message. Expected either "
                               "`content` or `choices[0].message.content`."),
                response_metadata={"keys": sorted(payload.keys())[:12]})
        if not text.strip():
            return InferenceResult(outcome=Outcome.EMPTY, upstream_status=status,
                                   latency_ms=latency,
                                   error_message="The endpoint returned an empty message.")

        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
        return InferenceResult(
            outcome=Outcome.OK, text=text,
            # The endpoint's own claim about which model answered. Recorded as
            # reported, never asserted by Prism: a black box cannot be made to
            # prove what is behind it.
            model_id=str(payload.get("model") or self.model_id),
            latency_ms=latency, upstream_status=status, usage=usage,
            finish_reason=str(payload.get("finishReason") or payload.get("finish_reason") or ""),
            request_metadata={"endpoint": self.base_url, "path": self._path},
            response_metadata={"model_reported_by_endpoint": payload.get("model")},
        )

    async def verify(self) -> VerificationResult:
        """A real generation. A reachable endpoint is not a working one."""
        result = await self.generate(
            [{"role": "user", "content": "Reply with the single word: ready."}],
            max_tokens=16, temperature=0.0)
        ok = result.ok and bool(result.text)
        if ok:
            detail = (f"Authenticated request succeeded in {result.latency_ms}ms "
                      f"(HTTP {result.upstream_status}).")
        else:
            detail = result.error_message or f"Endpoint did not answer ({result.outcome.value})."
        state = "verified" if ok else ("blocked" if result.outcome is Outcome.BLOCKED else "failed")
        return VerificationResult(
            verified=ok, state=state, outcome=result.outcome, detail=detail,
            model_id=result.model_id, latency_ms=result.latency_ms,
            upstream_status=result.upstream_status,
            response_excerpt=(result.text or "")[:200] or None,
        )
