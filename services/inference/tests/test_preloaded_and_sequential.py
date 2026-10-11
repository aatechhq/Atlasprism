"""Preloaded-model path and sequential execution."""
from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from natlas_inference import app as app_module
from natlas_inference.config import Config
from natlas_inference.engine import Generation, PreloadedEngine

KEY = "test-inference-key"
AUTH = {"Authorization": f"Bearer {KEY}"}


class FakeTokenizer:
    pad_token_id = 0
    pad_token = "<pad>"
    eos_token = "<eos>"
    chat_template = None


def test_preloaded_engine_reports_loaded_and_never_reloads():
    """The Colab guarantee: attaching must not trigger a download."""
    model, tok = object(), FakeTokenizer()
    engine = PreloadedEngine(model, tok, model_id="NCAIR1/N-ATLaS")
    assert engine.loaded is True
    assert engine.model_id == "NCAIR1/N-ATLaS"
    assert engine.load() is None  # no-op, not a reload
    assert engine._model is model, "must serve the exact object it was given"
    assert engine._tokenizer is tok


def test_preloaded_engine_requires_real_objects():
    with pytest.raises(ValueError):
        PreloadedEngine(None, FakeTokenizer())
    with pytest.raises(ValueError):
        PreloadedEngine(object(), None)


def test_preloaded_engine_shares_generation_code():
    """One implementation, two ways of obtaining the model."""
    from natlas_inference.engine import TransformersEngine

    assert PreloadedEngine.generate is TransformersEngine.generate
    assert PreloadedEngine._build_prompt is TransformersEngine._build_prompt


def test_attach_preloaded_configures_the_service():
    app_module.set_config(Config(
        api_key="", hf_token="", model_id="placeholder", load_in_4bit=True,
        max_new_tokens=256, allow_cpu=True, preload=True,
    ))
    app_module.attach_preloaded(object(), FakeTokenizer(),
                                model_id="NCAIR1/N-ATLaS", api_key=KEY)
    try:
        assert app_module.CONFIG.api_key == KEY
        assert app_module.CONFIG.model_id == "NCAIR1/N-ATLaS"
        assert app_module.CONFIG.preload is False, "must not preload an attached model"
        assert isinstance(app_module.ENGINE, PreloadedEngine)
    finally:
        app_module.set_engine(None)


def test_attach_preloaded_refuses_without_a_key():
    app_module.set_config(Config(
        api_key="", hf_token="", model_id="m", load_in_4bit=False,
        max_new_tokens=16, allow_cpu=True, preload=False,
    ))
    with pytest.raises(RuntimeError, match="open proxy"):
        app_module.attach_preloaded(object(), FakeTokenizer())


class SlowEngine:
    """Records overlap so the test can prove requests did not run in parallel."""

    model_id = "NCAIR1/N-ATLaS"
    loaded = True

    def __init__(self, delay=0.15):
        self.delay = delay
        self.live = 0
        self.peak = 0
        self.order = []
        self._guard = threading.Lock()

    def load(self):
        pass

    def generate(self, messages, *, max_new_tokens, temperature, language=None):
        with self._guard:
            self.live += 1
            self.peak = max(self.peak, self.live)
        time.sleep(self.delay)
        with self._guard:
            self.live -= 1
        text = messages[-1]["content"]
        self.order.append(text)
        return Generation(text=f"echo: {text}", finish_reason="stop",
                          prompt_tokens=3, completion_tokens=3, latency_ms=int(self.delay * 1000))


@pytest.fixture
def slow_client():
    engine = SlowEngine()
    app_module.set_config(Config(
        api_key=KEY, hf_token="", model_id="NCAIR1/N-ATLaS", load_in_4bit=True,
        max_new_tokens=256, allow_cpu=True, preload=False,
    ))
    app_module.set_engine(engine)
    with TestClient(app_module.app) as c:
        yield c, engine
    app_module.set_engine(None)


def test_concurrent_requests_execute_sequentially(slow_client):
    """A T4 cannot decode two 8B generations at once; the service must queue."""
    client, engine = slow_client
    results = []

    def fire(n):
        r = client.post("/v1/chat/completions", headers=AUTH, json={
            "messages": [{"role": "user", "content": f"req-{n}"}], "max_tokens": 8,
        })
        results.append(r.status_code)

    threads = [threading.Thread(target=fire, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert results == [200, 200, 200, 200]
    assert engine.peak == 1, f"generations overlapped (peak {engine.peak}); T4 would contend"
    assert len(engine.order) == 4


def test_health_reports_sequential_execution(slow_client):
    client, _ = slow_client
    body = client.get("/health").json()
    assert body["execution"] == "sequential (one generation at a time)"
    assert body["busy"] is False
    assert body["model_loaded"] is True
