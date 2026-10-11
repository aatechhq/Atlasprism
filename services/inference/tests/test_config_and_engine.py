"""Config and engine-guard tests. No torch required."""
from __future__ import annotations

import pytest

from natlas_inference.config import Config
from natlas_inference.engine import TransformersEngine


def test_config_defaults(monkeypatch):
    for var in ("INFERENCE_API_KEY", "HF_TOKEN", "MODEL_ID", "LOAD_IN_4BIT",
                "MAX_NEW_TOKENS", "ALLOW_CPU", "PRELOAD"):
        monkeypatch.delenv(var, raising=False)
    c = Config.from_env()
    assert c.model_id == "NCAIR1/N-ATLaS"
    assert c.load_in_4bit is True
    assert c.max_new_tokens == 256
    assert c.allow_cpu is False
    assert c.preload is True


def test_config_reads_environment(monkeypatch):
    monkeypatch.setenv("INFERENCE_API_KEY", "k")
    monkeypatch.setenv("MODEL_ID", "other/model")
    monkeypatch.setenv("LOAD_IN_4BIT", "0")
    monkeypatch.setenv("ALLOW_CPU", "yes")
    c = Config.from_env()
    assert (c.api_key, c.model_id, c.load_in_4bit, c.allow_cpu) == ("k", "other/model", False, True)


def test_service_refuses_to_start_without_a_key():
    c = Config(api_key="", hf_token="", model_id="m", load_in_4bit=True,
               max_new_tokens=16, allow_cpu=True, preload=False)
    with pytest.raises(RuntimeError, match="open proxy"):
        c.require_api_key()


def test_engine_constructs_without_importing_torch():
    """Importing/constructing must be free: no model download on a laptop."""
    e = TransformersEngine("NCAIR1/N-ATLaS", hf_token="", load_in_4bit=True)
    assert e.loaded is False
    assert e.model_id == "NCAIR1/N-ATLaS"


def test_engine_refuses_cpu_load_unless_explicitly_allowed():
    """The laptop guard: no accidental 8B CPU load."""
    torch = pytest.importorskip("torch")
    if torch.cuda.is_available():
        pytest.skip("CUDA present; the CPU guard does not apply here")
    e = TransformersEngine("NCAIR1/N-ATLaS", allow_cpu=False)
    with pytest.raises(RuntimeError, match="must run on a GPU host"):
        e.load()
