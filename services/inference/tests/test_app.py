"""HTTP contract tests. No model is downloaded: the engine is a stub."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from natlas_inference import app as app_module
from natlas_inference.config import Config
from natlas_inference.engine import Generation

KEY = "test-inference-key"
AUTH = {"Authorization": f"Bearer {KEY}"}


class StubEngine:
    """Records calls and returns a fixed generation. Clearly a fixture."""

    model_id = "NCAIR1/N-ATLaS"

    def __init__(self, text="Sannu da zuwa!", fail=False):
        self._text = text
        self._fail = fail
        self.calls = []
        self._loaded = True

    @property
    def loaded(self):
        return self._loaded

    def load(self):
        self._loaded = True

    def generate(self, messages, *, max_new_tokens, temperature, language=None):
        self.calls.append({"messages": messages, "max_new_tokens": max_new_tokens,
                           "temperature": temperature, "language": language})
        if self._fail:
            raise RuntimeError("no CUDA GPU detected")
        return Generation(text=self._text, finish_reason="stop", prompt_tokens=12,
                          completion_tokens=7, latency_ms=340)


@pytest.fixture
def engine():
    return StubEngine()


@pytest.fixture
def client(engine):
    app_module.set_config(Config(
        api_key=KEY, hf_token="", model_id="NCAIR1/N-ATLaS", load_in_4bit=True,
        max_new_tokens=256, allow_cpu=True, preload=False,
    ))
    app_module.set_engine(engine)
    with TestClient(app_module.app) as c:
        yield c
    app_module.set_engine(None)


def test_health_is_open_and_states_its_scope(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["model_id"] == "NCAIR1/N-ATLaS"
    assert body["quantization"] == "nf4-4bit"
    assert "not evidence of a successful generation" in body["note"]


def test_v1_routes_require_the_bearer_key(client):
    assert client.get("/v1/models").status_code == 401
    assert client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "hi"}]}).status_code == 401


def test_wrong_key_rejected_with_same_message_as_missing(client):
    a = client.get("/v1/models")
    b = client.get("/v1/models", headers={"Authorization": "Bearer wrong"})
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_models_lists_the_served_model(client):
    body = client.get("/v1/models", headers=AUTH).json()
    assert body["data"][0]["id"] == "NCAIR1/N-ATLaS"
    assert body["data"][0]["loaded"] is True


def test_chat_completion_returns_both_shapes(client):
    r = client.post("/v1/chat/completions", headers=AUTH, json={
        "model": "NCAIR1/N-ATLaS",
        "messages": [{"role": "user", "content": "Sannu!"}],
        "language": "ha",
        "max_tokens": 64,
    })
    assert r.status_code == 200
    body = r.json()
    # Flat shape, as the quickstart documents.
    assert body["content"] == "Sannu da zuwa!"
    assert body["role"] == "assistant"
    assert body["finishReason"] == "stop"
    assert body["model"] == "NCAIR1/N-ATLaS"
    assert body["usage"] == {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19}
    # OpenAI-compatible mirror.
    assert body["choices"][0]["message"]["content"] == "Sannu da zuwa!"
    assert body["choices"][0]["finish_reason"] == "stop"


def test_language_and_limits_are_passed_through(client, engine):
    client.post("/v1/chat/completions", headers=AUTH, json={
        "messages": [{"role": "user", "content": "hi"}],
        "language": "ig", "max_tokens": 32, "temperature": 0.1,
    })
    call = engine.calls[-1]
    assert call["language"] == "ig"
    assert call["max_new_tokens"] == 32
    assert call["temperature"] == 0.1


def test_max_tokens_cannot_exceed_the_service_cap(client, engine):
    client.post("/v1/chat/completions", headers=AUTH, json={
        "messages": [{"role": "user", "content": "hi"}], "max_tokens": 2048,
    })
    assert engine.calls[-1]["max_new_tokens"] == 256


def test_wrong_model_id_is_rejected_not_silently_served(client):
    r = client.post("/v1/chat/completions", headers=AUTH, json={
        "model": "gpt-4", "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 400
    assert r.json()["detail"]["served_model"] == "NCAIR1/N-ATLaS"


def test_empty_messages_rejected(client):
    assert client.post("/v1/chat/completions", headers=AUTH,
                       json={"messages": []}).status_code == 422


def test_bad_role_rejected(client):
    r = client.post("/v1/chat/completions", headers=AUTH, json={
        "messages": [{"role": "root", "content": "hi"}]})
    assert r.status_code == 422


def test_generation_failure_is_503_not_a_fake_completion():
    app_module.set_config(Config(
        api_key=KEY, hf_token="", model_id="NCAIR1/N-ATLaS", load_in_4bit=True,
        max_new_tokens=256, allow_cpu=False, preload=False,
    ))
    app_module.set_engine(StubEngine(fail=True))
    with TestClient(app_module.app) as c:
        r = c.post("/v1/chat/completions", headers=AUTH, json={
            "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 503
    assert "Generation unavailable" in r.json()["detail"]["error"]
    app_module.set_engine(None)


def test_service_without_a_key_refuses_to_serve_v1():
    app_module.set_config(Config(
        api_key="", hf_token="", model_id="m", load_in_4bit=False,
        max_new_tokens=16, allow_cpu=True, preload=False,
    ))
    app_module.set_engine(StubEngine())
    client = TestClient(app_module.app)
    r = client.get("/v1/models", headers=AUTH)
    assert r.status_code == 503
    app_module.set_engine(None)
