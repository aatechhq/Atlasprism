"""Connector tests: normalization, every error class, and no secret leakage."""
from __future__ import annotations

import httpx
import pytest
import respx

from app.connectors.base import Outcome
from app.connectors.natlas import CHAT_PATH, NatlasConnector

BASE = "https://gateway.example.invalid"
KEY = "test-key-ABCD1234"


def conn(**kw):
    return NatlasConnector(base_url=BASE, api_key=KEY, model_id="NCAIR1/N-ATLaS",
                           allowed_hosts={"gateway.example.invalid"}, **kw)


# --- guards before any call ---

def test_missing_base_url_is_blocked():
    c = NatlasConnector(base_url="", api_key=KEY, allowed_hosts=set())
    assert "base URL" in (c._blocked_reason() or "")


def test_missing_key_is_blocked_not_failed():
    c = NatlasConnector(base_url=BASE, api_key="", allowed_hosts={"gateway.example.invalid"})
    reason = c._blocked_reason() or ""
    assert "BLOCKED" in reason and "not simulated" in reason


def test_non_allowlisted_host_is_refused_ssrf():
    c = NatlasConnector(base_url="https://attacker.example.com", api_key=KEY,
                        allowed_hosts={"gateway.example.invalid"})
    assert "not in NATLAS_ALLOWED_HOSTS" in (c._blocked_reason() or "")


async def test_blocked_generate_makes_no_request():
    c = NatlasConnector(base_url=BASE, api_key="", allowed_hosts={"gateway.example.invalid"})
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(f"{BASE}{CHAT_PATH}").mock(return_value=httpx.Response(200))
        r = await c.generate([{"role": "user", "content": "hi"}])
    assert r.outcome is Outcome.BLOCKED
    assert not route.called, "a blocked connector must not contact the gateway"


# --- response shape normalization ---

def test_extract_text_flat_documented_shape():
    assert NatlasConnector._extract_text({"content": "hello"}) == ("hello", "flat")


def test_extract_text_openai_nested_shape():
    body = {"choices": [{"message": {"role": "assistant", "content": "hello"}}]}
    assert NatlasConnector._extract_text(body) == ("hello", "openai-nested")


def test_extract_text_unrecognised():
    text, shape = NatlasConnector._extract_text({"unexpected": True})
    assert text is None and shape == "unrecognised"


@respx.mock
async def test_successful_generation_normalizes_fields():
    respx.post(f"{BASE}{CHAT_PATH}").mock(return_value=httpx.Response(
        200,
        json={"content": "Abuja", "role": "assistant", "finishReason": "stop",
              "model": "NCAIR1/N-ATLaS", "usage": {"total_tokens": 7}},
        headers={"x-request-id": "req-123"},
    ))
    r = await conn().generate([{"role": "user", "content": "capital?"}], language="ha")
    assert r.outcome is Outcome.OK and r.ok
    assert r.text == "Abuja"
    assert r.model_id == "NCAIR1/N-ATLaS"
    assert r.finish_reason == "stop"
    assert r.usage == {"total_tokens": 7}
    assert r.upstream_status == 200
    assert r.request_id == "req-123"
    assert r.latency_ms is not None and r.latency_ms >= 0
    assert r.response_metadata["shape"] == "flat"


@respx.mock
async def test_request_body_matches_documented_contract():
    route = respx.post(f"{BASE}{CHAT_PATH}").mock(
        return_value=httpx.Response(200, json={"content": "ok"}))
    await conn().generate([{"role": "user", "content": "Sannu!"}], language="ha")
    sent = route.calls.last.request
    import json as _json

    body = _json.loads(sent.content)
    assert body["model"] == "NCAIR1/N-ATLaS"
    assert body["messages"] == [{"role": "user", "content": "Sannu!"}]
    assert body["language"] == "ha"
    assert sent.headers["authorization"] == f"Bearer {KEY}"


@respx.mock
async def test_request_metadata_never_contains_the_key():
    respx.post(f"{BASE}{CHAT_PATH}").mock(return_value=httpx.Response(200, json={"content": "x"}))
    r = await conn().generate([{"role": "user", "content": "hi"}])
    assert r.request_metadata["auth"] == "bearer <redacted>"
    assert KEY not in str(r.request_metadata)
    assert KEY not in str(r.response_metadata)


# --- error taxonomy: each class is distinct ---

@pytest.mark.parametrize("status,expected", [
    (401, Outcome.AUTH),
    (403, Outcome.AUTH),
    (404, Outcome.NOT_FOUND),
    (400, Outcome.BAD_REQUEST),
    (429, Outcome.RATE_LIMIT),
    (500, Outcome.UPSTREAM_ERROR),
    (503, Outcome.UPSTREAM_ERROR),
])
@respx.mock
async def test_http_error_statuses_map_to_distinct_outcomes(status, expected):
    respx.post(f"{BASE}{CHAT_PATH}").mock(return_value=httpx.Response(status, text="nope"))
    r = await conn().generate([{"role": "user", "content": "hi"}])
    assert r.outcome is expected
    assert not r.ok
    assert r.upstream_status == status
    assert KEY not in (r.error_message or "")


@respx.mock
async def test_auth_failure_message_leaks_no_credential():
    respx.post(f"{BASE}{CHAT_PATH}").mock(
        return_value=httpx.Response(401, text=f"bad key {KEY}"))
    r = await conn().generate([{"role": "user", "content": "hi"}])
    assert r.outcome is Outcome.AUTH
    # The upstream echoed the key; our error message must not carry it.
    assert KEY not in (r.error_message or "")


@respx.mock
async def test_timeout_is_its_own_outcome():
    respx.post(f"{BASE}{CHAT_PATH}").mock(side_effect=httpx.ReadTimeout("too slow"))
    r = await conn().generate([{"role": "user", "content": "hi"}])
    assert r.outcome is Outcome.TIMEOUT
    assert r.latency_ms is not None


@respx.mock
async def test_network_failure_is_its_own_outcome():
    respx.post(f"{BASE}{CHAT_PATH}").mock(side_effect=httpx.ConnectError("dns"))
    r = await conn().generate([{"role": "user", "content": "hi"}])
    assert r.outcome is Outcome.NETWORK


@respx.mock
async def test_non_json_2xx_is_schema_error():
    respx.post(f"{BASE}{CHAT_PATH}").mock(return_value=httpx.Response(200, text="<html>"))
    r = await conn().generate([{"role": "user", "content": "hi"}])
    assert r.outcome is Outcome.SCHEMA


@respx.mock
async def test_unrecognised_2xx_shape_is_schema_error():
    respx.post(f"{BASE}{CHAT_PATH}").mock(return_value=httpx.Response(200, json={"foo": "bar"}))
    r = await conn().generate([{"role": "user", "content": "hi"}])
    assert r.outcome is Outcome.SCHEMA
    assert "did not match the documented contract" in (r.error_message or "")


@respx.mock
async def test_empty_completion_is_its_own_outcome():
    respx.post(f"{BASE}{CHAT_PATH}").mock(return_value=httpx.Response(200, json={"content": "   "}))
    r = await conn().generate([{"role": "user", "content": "hi"}])
    assert r.outcome is Outcome.EMPTY


@respx.mock
async def test_model_mismatch_is_recorded_not_hidden():
    respx.post(f"{BASE}{CHAT_PATH}").mock(return_value=httpx.Response(
        200, json={"content": "hi", "model": "some-other-model"}))
    r = await conn().generate([{"role": "user", "content": "hi"}])
    assert r.ok
    assert r.response_metadata["model_mismatch"]["reported"] == "some-other-model"


# --- verify() ---

@respx.mock
async def test_verify_requires_real_generation():
    respx.post(f"{BASE}{CHAT_PATH}").mock(return_value=httpx.Response(
        200, json={"content": "ready", "model": "NCAIR1/N-ATLaS"}))
    v = await conn().verify()
    assert v.verified and v.state == "verified"
    assert "Authenticated inference succeeded" in v.detail


@respx.mock
async def test_verify_fails_closed_on_auth_error():
    respx.post(f"{BASE}{CHAT_PATH}").mock(return_value=httpx.Response(401))
    v = await conn().verify()
    assert not v.verified and v.state == "failed"


async def test_verify_is_blocked_without_credentials():
    c = NatlasConnector(base_url=BASE, api_key="", allowed_hosts={"gateway.example.invalid"})
    v = await c.verify()
    assert not v.verified and v.state == "blocked"


@respx.mock
async def test_health_is_never_verification():
    """A healthy gateway must not be reportable as a verified integration."""
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    out = await conn().health()
    assert out["reachable"] is True
    assert "not integration evidence" in out["note"]
    assert "verified" not in out
