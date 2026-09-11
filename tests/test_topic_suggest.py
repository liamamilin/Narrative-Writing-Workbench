"""Topic-suggestion (taxonomy v3 + /topics/suggest) tests.

Taxonomy v3: domains = flat Surface Domains; tensions = global cross-domain
goal-conflict axes; objects = 18 anchor groups. UI exposes only the domain
(v4): objects/tensions are engine-internal production resources; a batch
of `count` topics (default 8) is produced per click and accumulates in
the list, with previously shown texts passed back via `avoid`. Product
rule under test: AI proposes, user accepts — candidates are only
returned; nothing is persisted, and Write still requires the user's click.
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


class CapturingTopicEngine(MockWritingEngine):
    def __init__(self):
        self.kw = None

    def suggest_topics(self, **kw):
        self.kw = kw
        return super().suggest_topics(**kw)


@pytest.fixture()
def client():
    return TestClient(create_app(Service(Database(":memory:"))))


@pytest.fixture()
def failing_client():
    return TestClient(create_app(
        Service(Database(":memory:"), engine=FailingTopicEngine())))


@pytest.fixture()
def capturing_client():
    eng = CapturingTopicEngine()
    return TestClient(create_app(Service(Database(":memory:"), engine=eng))), eng


def test_taxonomy_v2_structure(client):
    t = client.get("/taxonomy").json()
    assert t["version"] >= 2
    doms, tens, objs = t["domains"], t["tensions"], t["objects"]
    assert len(doms) >= 45 and len(tens) >= 30
    assert len(objs) >= 18                                   # O-groups
    assert sum(len(g["items"]) for g in objs) >= 250         # object anchors
    assert {g["id"] for g in objs} >= {"O01", "O18"}
    assert {d["id"] for d in doms} >= {"politics", "education", "ai", "love"}
    assert {x["id"] for x in tens} >= {"t01", "t33"}
    assert len({d["id"] for d in doms}) == len(doms)       # unique ids
    assert len({x["id"] for x in tens}) == len(tens)
    assert all(d["name"] and x["name"] for d in doms for x in tens)
    assert all(g["name"] and g["items"] for g in objs)


def test_mock_pool_covers_every_domain_and_tension():
    tax = json.loads((Path(__file__).resolve().parents[1]
                      / "workbench" / "taxonomy.json").read_text("utf-8"))
    for d in tax["domains"]:
        hits = [t for t in _MOCK_TOPICS if d["id"] in t["domains"]]
        assert len(hits) >= 3, f"domain {d['id']} under-covered"
    for x in tax["tensions"]:
        hits = [t for t in _MOCK_TOPICS if x["id"] in t["tensions"]]
        assert len(hits) >= 2, f"tension {x['id']} under-covered"


def test_suggest_default_batch_of_eight(client):
    r = client.post("/topics/suggest", json={})
    assert r.status_code == 200, r.text
    topics = r.json()["topics"]
    assert len(topics) == 8
    assert validate_topics({"topics": topics}) == []
    assert len({t["text"] for t in topics}) == 8            # distinct


def test_suggest_count_param(client):
    r = client.post("/topics/suggest", json={"count": 5})
    assert r.status_code == 200
    assert len(r.json()["topics"]) == 5
    for bad in (2, 13, "8", True, 8.5):
        r = client.post("/topics/suggest", json={"count": bad})
        assert r.status_code == 400


def test_suggest_hint_reaches_engine(capturing_client):
    tc, eng = capturing_client
    r = tc.post("/topics/suggest",
                json={"hint": "关注外卖骑手", "count": 5})
    assert r.status_code == 200
    assert eng.kw["hint"] == "关注外卖骑手" and eng.kw["count"] == 5


def test_suggest_hint_too_long_rejected(client):
    r = client.post("/topics/suggest", json={"hint": "x" * 101})
    assert r.status_code == 400


def test_suggest_seed_reaches_engine(capturing_client):
    tc, eng = capturing_client
    seed = "女人会爱上伤害她的男人,却不会爱上对她好的男人"
    r = tc.post("/topics/suggest", json={"seed": seed, "count": 8})
    assert r.status_code == 200
    assert eng.kw["seed"] == seed


def test_suggest_seed_too_long_rejected(client):
    r = client.post("/topics/suggest", json={"seed": "x" * 201})
    assert r.status_code == 400


def test_mock_seed_filters_pool():
    from workbench.engine.mock import _MockTopicState
    _MockTopicState.reset()
    eng = MockWritingEngine()
    seed = "AA"
    hits = [t for t in _MOCK_TOPICS
            if seed in t["text"] or seed in t["hook"]]
    out = eng.suggest_topics(seed=seed)
    if hits:                                   # substring hits -> filtered
        assert {t["text"] for t in out["topics"]} <= {
            t["text"] for t in hits}
    else:                                      # no hits -> roam
        assert len(out["topics"]) >= 3


def test_suggest_respects_domain_filter(client):
    from workbench.engine.mock import _MOCK_TOPICS
    r = client.post("/topics/suggest", json={"domain": "labor"})
    topics = r.json()["topics"]
    pool = {t["text"] for t in _MOCK_TOPICS if "labor" in t["domains"]}
    assert 3 <= len(topics) <= 8                    # capped at pool size
    assert {t["text"] for t in topics} <= pool


def test_suggest_respects_tension_filter(client):
    r = client.post("/topics/suggest", json={"tension": "t03"})   # 自由↔安全
    topics = r.json()["topics"]
    pool = [t for t in _MOCK_TOPICS if "t03" in t["tensions"]]
    assert 3 <= len(topics) <= 8
    assert {t["text"] for t in topics} <= {t["text"] for t in pool}


def test_suggest_avoid_honored_and_reroll_differs(client):
    first = client.post("/topics/suggest", json={}).json()["topics"]
    r = client.post("/topics/suggest",
                    json={"avoid": [t["text"] for t in first]})
    second = r.json()["topics"]
    assert len(second) == 8
    assert not {t["text"] for t in first} & {t["text"] for t in second}


def test_suggest_accumulating_batches_all_distinct(client):
    """UI append semantics: N clicks -> all batches pairwise disjoint."""
    seen = []
    for _ in range(3):
        r = client.post("/topics/suggest", json={"avoid": seen})
        topics = r.json()["topics"]
        assert not {t["text"] for t in topics} & set(seen)
        seen += [t["text"] for t in topics]
    assert len(set(seen)) == len(seen) == 24


def test_suggest_unknown_category_rejected(client):
    r = client.post("/topics/suggest", json={"domain": "nope"})
    assert r.status_code == 400
    r = client.post("/topics/suggest", json={"tension": "t99"})
    assert r.status_code == 400
    r = client.post("/topics/suggest", json={"object": "不存在的对象"})
    assert r.status_code == 400
    r = client.post("/topics/suggest", json={"object": "算法"})
    assert r.status_code == 200


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
    """RealWritingEngine runs a validated structured call for topics.

    v4: engine samples `count` distinct tension axes and injects them;
    UI-only params (domain, count, hint, avoid) reach the prompt.
    """
    from app.config import Config
    from app.llm_client import MockClient
    from workbench.engine.real import RealWritingEngine

    texts = [f"这是第{i}个可争论的话题,针对不同对象{i}。" for i in range(1, 9)]
    hooks = [f"钩子{i}" for i in range(1, 9)]
    good = json.dumps({"topics": [
        {"text": t, "hook": h} for t, h in zip(texts, hooks)]},
        ensure_ascii=False)
    eng = RealWritingEngine.__new__(RealWritingEngine)   # no settings/env coupling
    eng.config = Config.default()
    eng.client = MockClient({"topic_suggest": [good]})
    out = eng.suggest_topics(domain="internet", hint="关注外卖骑手",
                             avoid=["旧的"])
    assert len(out["topics"]) == 8
    call = eng.client.calls[0]
    assert call["role"] == "topic_suggest"
    user = call["messages"][1]["content"]
    assert "internet" in user and "关注外卖骑手" in user and "旧的" in user
    assert "## Batch size\n\n8" in user
    axes_block = user.split("Required tension axes")[1].split("##")[0]
    axes = [ln.lstrip("- ").strip()
            for ln in axes_block.splitlines() if ln.strip().startswith("- ")]
    assert len(axes) == len(set(axes)) == 8
    tax = json.loads((Path(__file__).resolve().parents[1]
                      / "workbench" / "taxonomy.json").read_text("utf-8"))
    assert set(axes) <= {t["name"] for t in tax["tensions"]}


def test_real_engine_count_and_tension_params():
    """Explicit single tension overrides sampled axes in the prompt."""
    from app.config import Config
    from app.llm_client import MockClient
    from workbench.engine.real import RealWritingEngine

    good = json.dumps({"topics": [
        {"text": f"可争论话题编号{i},各有不同锚点。", "hook": f"钩子{i}"}
        for i in range(1, 6)]}, ensure_ascii=False)
    eng = RealWritingEngine.__new__(RealWritingEngine)
    eng.config = Config.default()
    eng.client = MockClient({"topic_suggest": [good]})
    out = eng.suggest_topics(count=5, tension="t08", object_name="算法")
    assert len(out["topics"]) == 5
    user = eng.client.calls[0]["messages"][1]["content"]
    assert "t08" in user and "算法" in user


def test_real_engine_avoid_injection_cap():
    """v5: the UI sends the whole library as avoid; prompt injects 24 max."""
    from app.config import Config
    from app.llm_client import MockClient
    from workbench.engine.real import RealWritingEngine

    good = json.dumps({"topics": [
        {"text": f"可争论话题编号{i}。", "hook": f"钩子{i}"}
        for i in range(1, 6)]}, ensure_ascii=False)
    eng = RealWritingEngine.__new__(RealWritingEngine)
    eng.config = Config.default()
    eng.client = MockClient({"topic_suggest": [good]})
    eng.suggest_topics(avoid=[f"已看过的话题{i}" for i in range(40)])
    user = eng.client.calls[0]["messages"][1]["content"]
    block = user.split("## Avoid")[1].split("##")[0]
    listed = [l for l in block.splitlines() if l.strip().startswith("- ")]
    assert len(listed) == 24


def test_real_engine_seed_mode_skips_axes():
    """v5.1: seed present -> no sampled tension axes, seed in prompt."""
    from app.config import Config
    from app.llm_client import MockClient
    from workbench.engine.real import RealWritingEngine

    good = json.dumps({"topics": [
        {"text": f"可争论话题编号{i},切面各不相同。", "hook": f"钩子{i}"}
        for i in range(1, 9)]}, ensure_ascii=False)
    eng = RealWritingEngine.__new__(RealWritingEngine)
    eng.config = Config.default()
    eng.client = MockClient({"topic_suggest": [good]})
    out = eng.suggest_topics(
        seed="女人会爱上伤害她的男人,却不会爱上对她好的男人")
    assert len(out["topics"]) == 8
    user = eng.client.calls[0]["messages"][1]["content"]
    assert "User seed" in user and "伤害" in user
    assert "Required tension axes" not in user


def test_schema_rejects_pseudo_depth_and_oversize():
    assert validate_topics({"topics": [
        {"text": "谈谈失败。", "hook": "话题太轻"},
        {"text": "让文章感人又有深度。", "hook": "假深刻"},
        {"text": "无意义的第三个话题", "hook": "占位"}]}) != []
    assert validate_topics({"topics": [
        {"text": "好话题" * 30, "hook": "过长被拒"},     # 90 > 80 chars
        {"text": "第二个可争论的话题", "hook": "张力清晰"},
        {"text": "第三个可争论的话题", "hook": "张力清晰"}]}) != []
    assert validate_topics({"topics": [
        {"text": f"可争论话题编号{i},锚点各不相同。", "hook": f"钩子{i}"}
        for i in range(1, 13)]}) == []                 # 12 allowed
    assert validate_topics({"topics": [
        {"text": f"可争论话题编号{i}。", "hook": f"钩子{i}"}
        for i in range(1, 14)]}) != []                 # 13 rejected
    assert validate_topics({"topics": [
        {"text": "同一句话说了两遍。", "hook": "重复一"},
        {"text": "同一句话说了两遍。", "hook": "重复二"},
        {"text": "第三个可争论的话题", "hook": "占位"}]}) != []   # dup text
    assert validate_topics({"topics": [                    # quote-variant dup
        {"text": "情侣把账算到分毫,信任反而更薄。", "hook": "公平与一体"},
        {"text": "情侣把账算到分毫，信任反而更薄。", "hook": "公平与一体"},
        {"text": "第三个可争论的话题", "hook": "占位"}]}) != []
