"""Topic-suggestion (taxonomy v2 + /topics/suggest) tests.

Taxonomy v2 (docs/TOPIC_TAXONOMY.md): domains = flat Surface Domains;
tensions = global cross-domain goal-conflict axes. Product rule under
test: AI proposes, user accepts — candidates are only returned; nothing
is persisted, and Write still requires the user's click.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench.api import create_app
from workbench.db import Database
from workbench.engine import EngineError
from workbench.engine.mock import MockWritingEngine, _MOCK_TOPICS
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


def test_taxonomy_v2_structure(client):
    t = client.get("/taxonomy").json()
    assert t["version"] >= 2
    doms, tens = t["domains"], t["tensions"]
    assert len(doms) >= 45 and len(tens) >= 30
    assert {d["id"] for d in doms} >= {"politics", "education", "ai", "love"}
    assert {x["id"] for x in tens} >= {"t01", "t33"}
    assert len({d["id"] for d in doms}) == len(doms)       # unique ids
    assert len({x["id"] for x in tens}) == len(tens)
    assert all(d["name"] and x["name"] for d in doms for x in tens)


def test_mock_pool_covers_every_domain_and_tension():
    tax = json.loads((Path(__file__).resolve().parents[1]
                      / "workbench" / "taxonomy.json").read_text("utf-8"))
    for d in tax["domains"]:
        hits = [t for t in _MOCK_TOPICS if d["id"] in t["domains"]]
        assert len(hits) >= 3, f"domain {d['id']} under-covered"
    for x in tax["tensions"]:
        hits = [t for t in _MOCK_TOPICS if x["id"] in t["tensions"]]
        assert len(hits) >= 2, f"tension {x['id']} under-covered"


def test_suggest_returns_three_with_hooks(client):
    r = client.post("/topics/suggest", json={})
    assert r.status_code == 200, r.text
    topics = r.json()["topics"]
    assert len(topics) == 3
    assert validate_topics({"topics": topics}) == []
    assert len({t["text"] for t in topics}) == 3            # distinct


def test_suggest_respects_domain_filter(client):
    from workbench.engine.mock import _MOCK_TOPICS
    r = client.post("/topics/suggest", json={"domain": "labor"})
    topics = r.json()["topics"]
    assert len(topics) == 3
    pool = {t["text"] for t in _MOCK_TOPICS if "labor" in t["domains"]}
    assert {t["text"] for t in topics} <= pool


def test_suggest_respects_tension_filter(client):
    r = client.post("/topics/suggest", json={"tension": "t03"})   # 自由↔安全
    topics = r.json()["topics"]
    assert len(topics) == 3
    pool = [t for t in _MOCK_TOPICS if "t03" in t["tensions"]]
    assert {t["text"] for t in topics} <= {t["text"] for t in pool}


def test_suggest_avoid_honored_and_reroll_differs(client):
    first = client.post("/topics/suggest", json={}).json()["topics"]
    r = client.post("/topics/suggest",
                    json={"avoid": [t["text"] for t in first]})
    second = r.json()["topics"]
    assert not {t["text"] for t in first} & {t["text"] for t in second}


def test_suggest_unknown_category_rejected(client):
    r = client.post("/topics/suggest", json={"domain": "nope"})
    assert r.status_code == 400
    r = client.post("/topics/suggest", json={"tension": "t99"})
    assert r.status_code == 400


def test_suggest_sub_alias_maps_to_tension(client):
    """Legacy v1 param name still works (rotation state reset for parity)."""
    from workbench.engine.mock import _MockTopicState
    _MockTopicState.reset()
    r1 = client.post("/topics/suggest", json={"tension": "t03"}).json()
    _MockTopicState.reset()
    r2 = client.post("/topics/suggest", json={"sub": "t03"}).json()
    assert ({t["text"] for t in r1["topics"]}
            == {t["text"] for t in r2["topics"]})


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
    out = eng.suggest_topics(domain="internet", tension="t08", avoid=["旧的"])
    assert len(out["topics"]) == 3 and out["topics"][0]["hook"]
    call = eng.client.calls[0]
    assert call["role"] == "topic_suggest"
    user = call["messages"][1]["content"]
    assert "internet" in user and "t08" in user and "旧的" in user


def test_schema_rejects_pseudo_depth_and_oversize():
    assert validate_topics({"topics": [
        {"text": "谈谈失败。", "hook": "话题太轻"},
        {"text": "让文章感人又有深度。", "hook": "假深刻"},
        {"text": "无意义的第三个话题", "hook": "占位"}]}) != []
    assert validate_topics({"topics": [
        {"text": "好话题" * 21, "hook": "过长被拒"},     # 63 > 60 chars
        {"text": "第二个可争论的话题", "hook": "张力清晰"},
        {"text": "第三个可争论的话题", "hook": "张力清晰"}]}) != []
