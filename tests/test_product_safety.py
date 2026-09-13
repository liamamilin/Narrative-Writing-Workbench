"""Product V0 hard-rule safety tests: revision safety, language safety,
and "no engine internals in the UI" (product/09, product/10)."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import RevisionClient as TestClient

from workbench.api import create_app
from workbench.db import Database
from workbench.engine import GenerationFailed, GenerateResult
from workbench.engine.mock import MockWritingEngine
from workbench.service import Service

STATIC = Path(__file__).resolve().parent.parent / "workbench" / "static"


class LeakyEngine(MockWritingEngine):
    """Pretends to be an engine that emits wrong-language or internal text."""

    def generate(self, **kw):
        if kw.get("config", {}).get("expected_language") == "zh":
            raise GenerationFailed("Language repair failed; generation rejected.")
        return GenerateResult(text="ok", plan={})


class InternalLeakEngine(MockWritingEngine):
    def review(self, **kw):
        return {"summary": {"progression": "WIR beats show strong reader_state"},
                "issues": []}


def _client(engine=None):
    return TestClient(create_app(Service(Database(":memory:"), engine=engine)))


def _task(c):
    return c.post("/tasks", json={
        "type": "fiction_scene", "instruction": "写一段。",
        "material": "素材。",
        "config": {"expected_language": "zh", "target_length": 200,
                   "locks": {"facts": True}}}).json()["id"]


# --------------------------------------------------- language safety ----

def test_wrong_language_generation_is_safely_rejected():
    c = _client(LeakyEngine())
    tid = _task(c)
    r = c.post(f"/tasks/{tid}/generate")
    assert r.status_code == 500
    err = r.json()["error"]
    assert err["code"] == "GENERATION_FAILED" and err["retryable"] is True
    t = c.get(f"/tasks/{tid}").json()
    assert t["draft"] is None          # nothing written
    assert t["status"] == "failed"


def test_language_failure_after_good_draft_keeps_it():
    c = _client(MockWritingEngine())
    tid = _task(c)
    g = c.post(f"/tasks/{tid}/generate").json()
    c.app.state.service.engine = LeakyEngine()
    assert c.post(f"/tasks/{tid}/generate").status_code == 500
    assert c.get(f"/tasks/{tid}").json()["draft"]["working_content"] == g["content"]


# ------------------------------------------------ internal leakage ----

def test_review_summary_is_translated_not_internal():
    c = _client(MockWritingEngine())
    tid = _task(c)
    c.post(f"/tasks/{tid}/generate")
    body = str(c.post(f"/tasks/{tid}/review").json())
    for leak in ("WIR", "wir_version", "reader_state", "Critic", "critic",
                 "beat", "Architect"):
        assert leak not in body


def test_api_task_detail_has_no_raw_plan():
    c = _client(MockWritingEngine())
    tid = _task(c)
    c.post(f"/tasks/{tid}/generate")
    body = str(c.get(f"/tasks/{tid}").json())
    for leak in ("wir_version", "reader_transition", "meaning_gain", "devices"):
        assert leak not in body


# ------------------------------------------- UI copy: no engine terms ----

@pytest.mark.parametrize("fname", ["index.html", "app.js", "styles.css"])
def test_static_ui_never_names_engine_internals(fname):
    text = (STATIC / fname).read_text(encoding="utf-8")
    for term in ("WIR", "Critic", "Patcher", "Architect", "Beat", "beat_id",
                 "reader_state", "chain-of-thought", "chain of thought"):
        assert term not in text, f"{fname} leaks {term}"


def test_index_served():
    c = _client()
    r = c.get("/")
    assert r.status_code == 200
    assert "Narrative Writing Workbench" in r.text


# ------------------------------------------------- golden path e2e ----

def test_full_golden_path(client_engine="mock"):
    c = _client()
    pid = c.post("/projects", json={"name": "P"}).json()["id"]
    tid = c.post("/tasks", json={
        "project_id": pid, "type": "fiction_scene", "title": "T",
        "instruction": "i", "material": "m" * 100,
        "config": {"expected_language": "en", "target_length": 300,
                   "locks": {"facts": True}}}).json()["id"]
    g = c.post(f"/tasks/{tid}/generate").json()
    c.post(f"/tasks/{tid}/review").json()
    pp = c.post(f"/tasks/{tid}/patch", json={
        "base_version_id": g["version_id"],
        "selection": {"paragraph_start": 1, "paragraph_end": 1},
        "instruction": "Make this shorter."}).json()
    a = c.post(f"/patches/{pp['patch_id']}/accept").json()
    vs = c.get(f"/drafts/{g['draft_id']}/versions").json()["versions"]
    assert [v["source_type"] for v in vs] == ["generation", "patch"]
    c.post(f"/versions/{vs[0]['id']}/restore")
    assert c.get(f"/tasks/{tid}").json()["draft"]["working_content"] == g["content"]
