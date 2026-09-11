"""Topic-suggestion (taxonomy + /topics/suggest) tests.

Product rule under test: AI proposes, user accepts — candidates are only
returned; nothing is persisted, and Write still requires the user's click.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from workbench.api import create_app
from workbench.db import Database
from workbench.engine import EngineError
from workbench.engine.mock import MockWritingEngine
from workbench.service import Service
from workbench.topic_schema import validate_topics


class FailingTopicEngine(MockWritingEngine):
    def suggest_topics(self, **kw):
        raise EngineError("topic coach unavailable")


@pytest.fixture()
def client():
    return TestClient(create_app(Service(Database(":memory:"))))


@pytest.fixture()
def failing_client():
    return TestClient(create_app(
        Service(Database(":memory:"), engine=FailingTopicEngine())))


def test_taxonomy_two_level(client):
    t = client.get("/taxonomy").json()
    assert len(t["domains"]) >= 8
    for d in t["domains"]:
        assert d["id"] and d["name"] and len(d["subs"]) >= 3
        for s in d["subs"]:
            assert s["id"].startswith(d["id"] + ".") and s["name"]


def test_suggest_returns_three_with_hooks(client):
    r = client.post("/topics/suggest", json={})
    assert r.status_code == 200, r.text
    topics = r.json()["topics"]
    assert len(topics) == 3
    assert validate_topics({"topics": topics}) == []
    texts = [t["text"] for t in topics]
    assert len(set(texts)) == 3            # distinct


def test_suggest_respects_domain_filter(client):
    from workbench.engine.mock import _MOCK_TOPICS
    work_texts = {t["text"] for t in _MOCK_TOPICS if t["domain"] == "work"}
    r = client.post("/topics/suggest", json={"domain": "work"})
    topics = r.json()["topics"]
    assert len(topics) == 3
    assert {t["text"] for t in topics} <= work_texts


def test_suggest_avoid_honored_and_reroll_differs(client):
    first = client.post("/topics/suggest", json={}).json()["topics"]
    r = client.post("/topics/suggest",
                    json={"avoid": [t["text"] for t in first]})
    second = r.json()["topics"]
    assert not {t["text"] for t in first} & {t["text"] for t in second}


def test_suggest_unknown_category_rejected(client):
    r = client.post("/topics/suggest", json={"domain": "nope"})
    assert r.status_code == 400
    r = client.post("/topics/suggest",
                    json={"domain": "work", "sub": "self.freedom"})
    assert r.status_code == 400


def test_suggest_engine_error_retryable(failing_client):
    r = failing_client.post("/topics/suggest", json={})
    assert r.status_code == 500
    err = r.json()["error"]
    assert err["code"] == "TOPIC_SUGGEST_FAILED" and err["retryable"] is True


def test_real_engine_topic_prompt_path():
    """RealWritingEngine runs a validated structured call for topics."""
    from app.config import Config
    from app.llm_client import MockClient
    from workbench.engine.real import RealWritingEngine

    good = ("{\"topics\": [{\"text\": \"越连接,越孤独。\", \"hook\": \"在线为何更冷\"},"
            " {\"text\": \"便利不是省时间。\", \"hook\": \"谁赚走耐心\"},"
            " {\"text\": \"快是新的慢。\", \"hook\": \"提速的代价\"}]}")
    eng = RealWritingEngine.__new__(RealWritingEngine)   # no settings/env coupling
    eng.config = Config.default()
    eng.client = MockClient({"topic_suggest": [good]})
    out = eng.suggest_topics(domain="tech", sub="tech.speed", avoid=["旧的"])
    assert len(out["topics"]) == 3 and out["topics"][0]["hook"]
    call = eng.client.calls[0]
    assert call["role"] == "topic_suggest"
    user = call["messages"][1]["content"]
    assert "tech.speed" in user and "旧的" in user
