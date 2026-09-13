"""AI-assisted Intent (suggest-intent) API tests.

Product rule under test: AI proposes, user accepts — the endpoint only
returns a suggestion; nothing is persisted unless the client PATCHes.
"""

from __future__ import annotations

import pytest
from conftest import RevisionClient as TestClient

from workbench.api import create_app
from workbench.db import Database
from workbench.engine import EngineError
from workbench.engine.mock import MockWritingEngine
from workbench.service import Service


class FailingSuggestEngine(MockWritingEngine):
    def suggest_instruction(self, **kw):
        raise EngineError("intent coach unavailable")


@pytest.fixture()
def svc():
    return Service(Database(":memory:"))


@pytest.fixture()
def client(svc):
    return TestClient(create_app(svc))


@pytest.fixture()
def failing_client():
    svc = Service(Database(":memory:"), engine=FailingSuggestEngine())
    return TestClient(create_app(svc))


def make_task(c, **over):
    body = {"type": "fiction_scene", "title": "Dinner",
            "material": "年夜饭上,父亲给我夹了一筷子鱼腹。",
            "config": {"expected_language": "zh"}}
    body.update(over)
    r = c.post("/tasks", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_suggest_intent_from_material(client):
    tid = make_task(client, instruction="")
    r = client.post(f"/tasks/{tid}/suggest-intent", json={})
    assert r.status_code == 200, r.text
    s = r.json()["suggestion"]
    assert isinstance(s, str) and s.strip()


def test_suggest_intent_with_existing_instruction(client):
    tid = make_task(client)
    r = client.post(f"/tasks/{tid}/suggest-intent", json={})
    assert r.status_code == 200, r.text
    assert r.json()["suggestion"]


def test_suggest_intent_accepts_avoid_list(client):
    tid = make_task(client, instruction="")
    r = client.post(f"/tasks/{tid}/suggest-intent",
                    json={"avoid": ["旧的想法"]})
    assert r.status_code == 200, r.text
    assert r.json()["suggestion"]


def test_suggest_intent_without_grist_rejected(svc, client):
    tid = make_task(client, instruction="")
    svc.db.exec("DELETE FROM task_sources WHERE task_id=?", (tid,))
    r = client.post(f"/tasks/{tid}/suggest-intent", json={})
    assert r.status_code == 409


def test_suggest_intent_engine_error_retryable(failing_client):
    tid = make_task(failing_client, instruction="")
    r = failing_client.post(f"/tasks/{tid}/suggest-intent", json={})
    assert r.status_code == 500
    err = r.json()["error"]
    assert err["retryable"] is True


def test_suggest_intent_does_not_persist(client):
    tid = make_task(client, instruction="")
    client.post(f"/tasks/{tid}/suggest-intent", json={})
    task = client.get(f"/tasks/{tid}").json()
    assert task["instruction"] == ""