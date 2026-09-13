"""Settings screen backend tests (V0.1.x: LLM config in the UI)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from workbench import settings as settings_mod
from workbench.api import create_app
from workbench.db import Database
from workbench.service import Service


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("WORKBENCH_ENGINE", raising=False)
    return path


def _client():
    return TestClient(create_app(Service(Database(":memory:"))))


def test_get_settings_shape():
    c = _client()
    s = c.get("/settings").json()
    assert s["engine"] == "mock"
    assert "api_key" not in s                      # never the full key
    assert set(s) >= {"engine", "base_url", "api_key_masked", "has_key",
                      "model", "timeout_seconds", "writer_temperature"}


def test_update_persists_masks_key_and_hot_swaps_engine():
    c = _client()
    r = c.post("/settings", json={
        "engine": "mock", "api_key": "sk-secret1234567890",
        "base_url": "https://x.test/v1", "model": "some-model"})
    assert r.status_code == 200
    s = r.json()
    assert s["api_key_masked"] == "sk-s…7890"
    assert "secret" not in str(s)
    assert s["has_key"] is True and s["model"] == "some-model"
    # persisted + applied to env
    assert json.loads((settings_mod.SETTINGS_PATH).read_text())["model"] == "some-model"
    import os
    assert os.environ["OPENAI_API_KEY"] == "sk-secret1234567890"


def test_empty_fields_keep_current_values():
    c = _client()
    c.post("/settings", json={"api_key": "sk-a1234567890b", "model": "m1"})
    c.post("/settings", json={"api_key": "", "model": ""})   # blanks keep
    s = c.get("/settings").json()
    assert s["model"] == "m1" and s["has_key"] is True


def test_invalid_engine_rejected():
    c = _client()
    assert c.post("/settings", json={"engine": "turbo"}).status_code == 400


def test_engine_mode_applies_to_new_service():
    settings_mod.save({"engine": "mock"})
    from workbench.engine import get_engine
    assert get_engine().name == "mock"


def test_real_workbench_engine_disables_implicit_provider_retries(monkeypatch):
    """The UI's per-call timeout must not be multiplied by SDK retries."""
    import openai
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    from workbench.engine.real import RealWritingEngine
    RealWritingEngine()
    assert captured["max_retries"] == 0


def test_test_connection_without_key_or_model(monkeypatch):
    # no config.live.yaml fallback: model must come from settings/payload only
    monkeypatch.setattr(settings_mod, "_model_from_config_yaml", lambda: None)
    c = _client()
    r = c.post("/settings/test", json={}).json()
    assert r["ok"] is False and "key" in r["error"].lower()
    r = c.post("/settings/test", json={"api_key": "sk-x"}).json()
    assert r["ok"] is False and "model" in r["error"].lower()


def test_test_connection_network_failure_is_graceful():
    c = _client()
    r = c.post("/settings/test", json={
        "api_key": "sk-fake", "base_url": "http://127.0.0.1:9/v1",
        "model": "nope"}).json()
    assert r["ok"] is False and r["error"]


# ------------------------------------------- provider presets + models ----

def test_providers_dropdown():
    c = _client()
    ps = c.get("/settings/providers").json()["providers"]
    ids = [p["id"] for p in ps]
    assert "ollama" in ids and "custom" in ids
    ollama = next(p for p in ps if p["id"] == "ollama")
    assert ollama["base_url"] == "http://127.0.0.1:11434/v1"
    assert ollama["needs_key"] is False


def test_fetch_models_missing_base():
    c = _client()
    r = c.post("/settings/models", json={}).json()
    assert r["ok"] is False


def test_fetch_models_local_ollama_gets_placeholder_key(monkeypatch):
    import openai
    captured = {}

    class FakeModels:
        def list(self):
            class D: data = [type("M", (), {"id": "llama3"})]
            return D()

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None, timeout=None,
                     default_headers=None):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            captured["default_headers"] = default_headers
        models = FakeModels()

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    c = _client()
    r = c.post("/settings/models",
               json={"base_url": "http://127.0.0.1:11434/v1"}).json()
    assert r["ok"] is True and r["models"] == ["llama3"]
    assert captured["api_key"] == "ollama"        # placeholder, no key needed


def test_fetch_models_unreachable_is_graceful():
    c = _client()
    r = c.post("/settings/models", json={
        "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-fake"}).json()
    assert r["ok"] is False and r["error"]


def test_bad_numeric_settings_rejected():
    c = _client()
    r = c.post("/settings", json={"timeout_seconds": "abc"})
    assert r.status_code == 400 and "timeout_seconds" in r.json()["error"]["message"]
    # Send the malformed body explicitly: newer HTTP clients reject NaN
    # before it reaches the server, which would not test our validation.
    r = c.post("/settings", content='{"writer_temperature": NaN}',
               headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and "writer_temperature" in r.json()["error"]["message"]
    r = c.post("/settings", json={"writer_temperature": 3})
    assert r.status_code == 400 and "0-2" in r.json()["error"]["message"]
    r = c.post("/settings", json={"timeout_seconds": None, "writer_temperature": None})
    assert r.status_code == 200                      # explicit reset allowed
