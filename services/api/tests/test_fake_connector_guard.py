"""The test-only connector must be impossible to use in a deployed process."""
from __future__ import annotations

import os

import pytest

from app.connectors.fake import ENV_FLAG, FakeConnector


def test_fake_connector_refuses_without_the_test_flag(monkeypatch):
    monkeypatch.delenv(ENV_FLAG, raising=False)
    with pytest.raises(RuntimeError, match="test-only"):
        FakeConnector()


def test_fake_connector_available_in_tests():
    assert os.environ.get(ENV_FLAG) == "1"
    assert FakeConnector(replies=["x"]).name.startswith("fake")


async def test_fake_connector_can_never_report_verification():
    v = await FakeConnector(replies=["x"]).verify()
    assert v.verified is False
    assert v.state == "blocked"


def test_no_production_module_imports_the_fake_connector():
    """Grep-level guarantee: only tests may reference it."""
    import pathlib

    app_dir = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = [
        p.relative_to(app_dir).as_posix()
        for p in app_dir.rglob("*.py")
        if p.name != "fake.py" and "connectors.fake" in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"production code imports the fake connector: {offenders}"
