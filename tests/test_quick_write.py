"""Quick Write V0.1 tests (docs/narrative-writing-product-v0.1-quick-write-spec).

Covers the 14 required tests from QUICK_WRITE_IMPLEMENTATION_TASK.md.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from workbench.api import create_app
from workbench.db import Database
from workbench.engine import DiscoveryFailed, GenerateResult
from workbench.engine.mock import MockWritingEngine
from workbench import meaning_schema
from workbench.service import Service, detect_fact_heavy


class SpyEngine(MockWritingEngine):
    """Records discovery/generate inputs for WIR-handoff assertions."""

    def __init__(self):
        self.generate_calls = []
        self.discover_calls = []

    def discover_meaning(self, **kw):
        self.discover_calls.append(kw)
        return super().discover_meaning(**kw)

    def generate(self, **kw):
        self.generate_calls.append(kw)
        return super().generate(**kw)


class BadDiscoveryEngine(MockWritingEngine):
    def discover_meaning(self, **kw):
        return {"topic": "x"}  # schema-invalid


class FailingDiscoveryEngine(MockWritingEngine):
    def discover_meaning(self, **kw):
        raise DiscoveryFailed("no angle found")


def _svc(engine=None):
    return Service(Database(":memory:"), engine=engine or MockWritingEngine())


def _client(engine=None):
    return TestClient(create_app(_svc(engine)))


def qw_task(c, **over):
    body = {"input_mode": "topic_only", "topic": "谈谈失败",
            "writing_mode": "deep_narrative", "angle_mode": "auto",
            "config": {"expected_language": "zh", "target_length": 900}}
    body.update(over)
    r = c.post("/tasks", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ------------------------------------------- 1. topic-only task creation ----

def test_topic_only_task_creation_and_defaults():
    c = _client()
    tid = qw_task(c)
    t = c.get(f"/tasks/{tid}").json()
    assert t["input_mode"] == "topic_only"
    assert t["topic"] == "谈谈失败"
    assert t["writing_mode"] == "deep_narrative"
    assert t["type"] == "essay"          # writing_mode mapped onto engine type
    # topic is enough: no instruction/material required
    assert c.post("/tasks", json={"input_mode": "topic_only"}).status_code == 400
    assert c.post("/tasks", json={"input_mode": "topic_only", "topic": "x",
                                  "angle_mode": "custom"}).status_code == 400


# --------------------------------------- 2. Meaning Discovery schema valid ----

def test_meaning_discovery_schema_valid():
    d = MockWritingEngine().discover_meaning(
        topic="谈谈失败", writing_mode="deep_narrative", angle_mode="auto",
        custom_angle="", avoid=[], config={})
    assert meaning_schema.validate_meaning(d) == []
    assert 3 <= len(d["candidate_angles"]) <= 5
    for f in ("topic", "selected_angle_id", "core_question", "deep_meaning",
              "reader_end_state"):
        assert d.get(f)


# ------------------------------- 3. invalid structured output -> repair ----

def test_invalid_discovery_rejected_and_retryable():
    c = _client(BadDiscoveryEngine())
    tid = qw_task(c)
    r = c.post(f"/tasks/{tid}/generate")
    assert r.status_code == 500
    err = r.json()["error"]
    assert err["code"] == "DISCOVERY_FAILED" and err["retryable"] is True
    # failure safety: no broken draft
    t = c.get(f"/tasks/{tid}").json()
    assert t["draft"] is None and t["status"] == "failed"


def test_discovery_engine_failure_retryable():
    c = _client(FailingDiscoveryEngine())
    tid = qw_task(c)
    r = c.post(f"/tasks/{tid}/generate")
    assert r.status_code == 500
    assert r.json()["error"]["retryable"] is True


def test_structured_repair_path_with_meaning_validator():
    """structured_call repairs once on schema-invalid output (Harness convention)."""
    from app.structured import structured_call
    from app.config import Config
    good = MockWritingEngine().discover_meaning(
        topic="t", writing_mode="deep_narrative", angle_mode="auto",
        custom_angle="", avoid=[], config={})

    class FakeClient:
        def __init__(self):
            self.calls = 0
        def generate_structured(self, messages, role, role_cfg):
            self.calls += 1
            text = "not json" if self.calls == 1 else json.dumps(good)
            class R: text_ = text
            r = R(); r.text = text
            r.input_tokens = r.output_tokens = r.latency_seconds = 0
            return r

    fc = FakeClient()
    cfg = Config.default()
    stage = structured_call(fc, role="meaning_discovery",
                            role_cfg=cfg.role("architect"),
                            system_prompt="s", user_message="u",
                            validator=meaning_schema.validate_meaning)
    assert fc.calls == 2 and stage.repair_used
    assert stage.data["selected_angle_id"] == good["selected_angle_id"]


# ---------------------------------------- 4. multiple distinct candidates ----

def test_candidates_must_be_distinct():
    d = MockWritingEngine().discover_meaning(
        topic="t", writing_mode="deep_narrative", angle_mode="auto",
        custom_angle="", avoid=[], config={})
    dup = json.loads(json.dumps(d))
    dup["candidate_angles"][1]["label"] = dup["candidate_angles"][0]["label"]
    errors = meaning_schema.validate_meaning(dup)
    assert any("duplicate" in e for e in errors)


# ------------------------------------------- 5. selected angle persisted ----

def test_selected_angle_persisted_with_lineage():
    db = Database(":memory:")
    svc = Service(db, engine=MockWritingEngine())
    c = TestClient(create_app(svc))
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate")
    rows = db.q("SELECT * FROM meaning_discoveries WHERE task_id=?", (tid,))
    assert len(rows) == 1 and rows[0]["status"] == "ready"
    data = json.loads(rows[0]["data_json"])
    assert rows[0]["selected_angle_id"] == data["selected_angle_id"]
    # lineage: engine plan points at the discovery row
    plan = db.q1("SELECT * FROM engine_plans WHERE task_id=?", (tid,))
    assert plan["meaning_id"] == rows[0]["id"]


# ------------------------------------- 6. WIR receives angle/deep meaning ----

def test_wir_receives_selected_meaning():
    spy = SpyEngine()
    c = _client(spy)
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate")
    assert len(spy.discover_calls) == 1
    gk = spy.generate_calls[0]
    meaning = gk["meaning"]
    assert meaning["selected_angle_id"] == meaning["candidate_angles"][-1]["id"]
    assert meaning["deep_meaning"]
    # the plan persisted with the draft carries the meaning handoff
    body = str(c.get(f"/tasks/{tid}").json())  # detail must not leak internals
    assert "selection_reason" not in body


def test_topic_instruction_block_contains_meaning():
    from workbench.engine.real import _compose_topic_instruction
    block = _compose_topic_instruction("我的想法", {
        "candidate_angles": [{"id": "A2", "label": "失败重新定价成本"}],
        "selected_angle_id": "A2",
        "core_question": "为什么失败会改变过去努力的意义?",
        "deep_meaning": "失败摧毁了为牺牲辩护的框架。",
        "reader_end_state": "读者把失败看作追溯性重估。",
        "key_tensions": ["投入 vs 幻灭"]})
    for s in ("失败重新定价成本", "为什么失败会改变过去努力的意义?",
              "失败摧毁了为牺牲辩护的框架。", "读者把失败看作追溯性重估。",
              "投入 vs 幻灭", "我的想法"):
        assert s in block


# --------------------------------------- 7. another angle reruns discovery ----

def test_try_another_angle_reruns_discovery_with_avoid_list():
    spy = SpyEngine()
    c = _client(spy)
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate")
    first = spy.discover_calls[0]
    r1 = c.get(f"/tasks/{tid}/meaning").json()
    r = c.post(f"/tasks/{tid}/rediscover-angle")
    assert r.status_code == 200, r.text
    assert len(spy.discover_calls) == 2
    avoid = spy.discover_calls[1]["avoid"]
    assert r1["selected_angle"] in avoid          # old angle is avoided
    r2 = c.get(f"/tasks/{tid}/meaning").json()
    assert r2["selected_angle"] != r1["selected_angle"]
    # a new version was created; old draft preserved in history
    vs = c.get(f"/drafts/{r.json()['draft_id']}/versions").json()["versions"]
    assert [v["source_type"] for v in vs] == ["generation", "generation"]


# ------------------------------------- 8. same-angle rewrite preserves angle ----

def test_rewrite_same_angle_preserves_angle():
    spy = SpyEngine()
    c = _client(spy)
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate")
    before = c.get(f"/tasks/{tid}/meaning").json()
    r = c.post(f"/tasks/{tid}/regenerate", json={"preserve_angle": True})
    assert r.status_code == 200
    assert len(spy.discover_calls) == 1           # discovery NOT rerun
    after = c.get(f"/tasks/{tid}/meaning").json()
    assert after == before                        # angle preserved
    assert spy.generate_calls[1]["meaning"]["selected_angle_id"] == \
        spy.generate_calls[0]["meaning"]["selected_angle_id"]
    # retry-only-for-topic_only guard
    sid = make_source_task(c)
    assert c.post(f"/tasks/{sid}/regenerate",
                  json={"preserve_angle": True}).status_code == 409


# ----------------------------- 9/10. source_grounded & draft_revision unchanged ----

def make_source_task(c):
    r = c.post("/tasks", json={"type": "essay",
                               "instruction": "写年夜饭。",
                               "material": "父亲夹菜。"})
    return r.json()["id"]


def test_source_grounded_flow_unchanged():
    spy = SpyEngine()
    c = _client(spy)
    tid = make_source_task(c)
    t = c.get(f"/tasks/{tid}").json()
    assert t["input_mode"] == "source_grounded"   # default back-compat
    assert c.post(f"/tasks/{tid}/generate").status_code == 200
    assert spy.discover_calls == []               # no discovery in old flow
    p = c.post(f"/tasks/{tid}/patch", json={
        "base_version_id": c.get(f"/tasks/{tid}").json()["draft"]["current_version_id"],
        "selection": {"paragraph_start": 1, "paragraph_end": 1},
        "instruction": "shorter"}).json()
    assert c.post(f"/patches/{p['patch_id']}/accept").status_code == 200
    assert c.get(f"/tasks/{tid}/meaning").status_code == 404


def test_draft_revision_flow_unchanged():
    c = _client()
    r = c.post("/tasks", json={"input_mode": "draft_revision", "type": "essay",
                               "instruction": "结尾太说教,收住。",
                               "material": "第一稿全文在此。\n\n他终于明白了。"})
    assert r.status_code == 200
    tid = r.json()["id"]
    assert r.json()["input_mode"] == "draft_revision"
    assert c.post(f"/tasks/{tid}/generate").status_code == 200


# ---------------------------------------------- 11. factuality warning ----

def test_factuality_detection():
    assert detect_fact_heavy("为什么罗马帝国灭亡？")
    assert detect_fact_heavy("2026 年中国人口发生了什么？")
    assert detect_fact_heavy("这家公司为什么裁员？")
    assert not detect_fact_heavy("谈谈失败")
    assert not detect_fact_heavy("为什么知道结局仍然会紧张？")


def test_factuality_warning_surface_and_continue():
    c = _client()
    tid = qw_task(c, topic="为什么罗马帝国灭亡？")
    assert c.get(f"/tasks/{tid}").json()["factuality_warning"] is True
    # Continue: generation still allowed without sources
    assert c.post(f"/tasks/{tid}/generate").status_code == 200


# ---------------------------------------------- 12. source transition ----

def test_adding_sources_transitions_mode_and_persists():
    db = Database(":memory:")
    c = TestClient(create_app(Service(db, engine=MockWritingEngine())))
    tid = qw_task(c)
    r = c.post(f"/tasks/{tid}/sources", json={"title": "笔记", "content": "一些事实素材。"})
    assert r.status_code == 200
    t = c.get(f"/tasks/{tid}").json()
    assert t["input_mode"] == "source_grounded"
    assert t["factuality_warning"] is False
    constraints = json.loads(db.q1(
        "SELECT constraints_json FROM writing_configs WHERE task_id=?", (tid,))
        ["constraints_json"])
    assert constraints["mode_transitions"] == [
        {"from": "topic_only", "to": "source_grounded",
         "at": constraints["mode_transitions"][0]["at"]}]


# ------------------------------------------ 13. core meaning lock defaults ON ----

def test_preserve_core_meaning_defaults_on():
    c = _client()
    tid = qw_task(c)
    t = c.get(f"/tasks/{tid}").json()
    assert t["config"]["locks"]["core_meaning"] is True


# -------------------------------------------------- 14. version lineage ----

def test_full_lineage_topic_to_version():
    db = Database(":memory:")
    c = TestClient(create_app(Service(db, engine=MockWritingEngine())))
    tid = qw_task(c)
    g = c.post(f"/tasks/{tid}/generate").json()
    task = db.q1("SELECT * FROM tasks WHERE id=?", (tid,))
    disc = db.q1("SELECT * FROM meaning_discoveries WHERE task_id=?", (tid,))
    plan = db.q1("SELECT * FROM engine_plans WHERE task_id=?", (tid,))
    ver = db.q1("SELECT * FROM versions WHERE id=?", (g["version_id"],))
    assert task["topic"] == "谈谈失败"
    assert plan["meaning_id"] == disc["id"]
    assert ver["source_type"] == "generation"
    c.post(f"/tasks/{tid}/regenerate", json={"preserve_angle": True})
    plan2 = db.q1("SELECT * FROM engine_plans WHERE task_id=? ORDER BY created_at DESC, id DESC LIMIT 1", (tid,))
    assert plan2["meaning_id"] == disc["id"]      # same angle reused
    vs = db.q("SELECT * FROM versions WHERE draft_id=? ORDER BY created_at", (ver["draft_id"],))
    assert vs[1]["parent_version_id"] == vs[0]["id"]  # chain intact


# --------------------------------------------- UI safety: meaning payload ----

def test_meaning_endpoint_product_safe():
    c = _client()
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate")
    body = str(c.get(f"/tasks/{tid}/meaning").json())
    for leak in ("WIR", "Architect", "Critic", "selection_reason",
                 "candidate_angles", "chain-of-thought"):
        assert leak not in body
    m = c.get(f"/tasks/{tid}/meaning").json()
    assert set(m) == {"topic", "selected_angle", "core_question", "reader_end_state"}


# ------------------------------------------------ SSE progress stream ----

def _sse_events(text: str) -> list[tuple[str, dict]]:
    out, kind, data = [], "", ""
    for line in text.splitlines():
        if line.startswith("event: "):
            kind = line[7:]
        elif line.startswith("data: "):
            data = line[6:]
        elif line == "" and kind:
            out.append((kind, json.loads(data)))
            kind, data = "", ""
    return out


def test_progress_stream_replays_stages_and_angle():
    c = _client()
    tid = qw_task(c)
    assert c.post(f"/tasks/{tid}/generate").status_code == 200
    r = c.get(f"/tasks/{tid}/progress")
    assert r.status_code == 200
    events = _sse_events(r.text)
    kinds = [k for k, _ in events]
    assert "stage" in kinds and "angle" in kinds
    stages = [e["data"]["stage"] for k, e in events if k == "stage"]
    assert stages == ["queued", "discovery", "structure", "writing"]
    assert events[-1][0] == "eof"
    # angle event carries only product-safe fields
    angle_ev = next(e for k, e in events if k == "angle")
    assert set(angle_ev["data"]) == {"topic", "selected_angle",
                                     "core_question", "reader_end_state"}


def test_progress_stream_error_event_on_failure():
    c = _client(FailingDiscoveryEngine())
    tid = qw_task(c)
    assert c.post(f"/tasks/{tid}/generate").status_code == 500
    events = _sse_events(c.get(f"/tasks/{tid}/progress").text)
    kinds = [k for k, _ in events]
    assert "error" in kinds and events[-1][0] == "eof"


def test_progress_404_for_unknown_task():
    c = _client()
    assert c.get("/tasks/nope/progress").status_code == 404


def test_progress_idle_task_returns_eof_immediately():
    c = _client()
    tid = qw_task(c)                     # never generated
    events = _sse_events(c.get(f"/tasks/{tid}/progress").text)
    assert events == [("eof", {"seq": -1, "kind": "eof"})]


# ------------------------------------------------ token-level streaming ----

def test_generate_streams_deltas_that_reconstruct_text():
    c = _client()
    tid = qw_task(c)
    assert c.post(f"/tasks/{tid}/generate").status_code == 200
    events = _sse_events(c.get(f"/tasks/{tid}/progress").text)
    deltas = [e["data"] for k, e in events if k == "delta"]
    assert deltas, "expected delta events on the progress stream"
    streamed = "".join(d.get("t", "") for d in deltas)
    content = c.get(f"/tasks/{tid}").json()["draft"]["working_content"]
    assert streamed == content
    first_delta = next(i for i, (k, _) in enumerate(events) if k == "delta")
    writing = next(i for i, (k, e) in enumerate(events)
                   if k == "stage" and e["data"]["stage"] == "writing")
    assert first_delta > writing          # deltas arrive only during writing
    assert events[-1][0] == "eof"


def test_mock_engine_on_delta_matches_final_text():
    from workbench.engine.mock import MockWritingEngine
    eng = MockWritingEngine()
    chunks = []
    res = eng.generate(material="m", instruction="i", task_type="essay",
                       config={}, on_delta=chunks.append)
    assert "".join(chunks) == res.text


def test_delta_stream_batches_flush_and_reset():
    from workbench.service import _delta_stream

    class Ch:
        def __init__(self):
            self.evts = []

        def emit(self, kind, data):
            self.evts.append((kind, data))

    ch = Ch()
    cb = _delta_stream(ch)
    cb("hello ")
    assert ch.evts == []                       # below batch threshold: buffered
    cb("world" * 10)
    assert ch.evts[0][0] == "delta"
    assert ch.evts[0][1]["t"].startswith("hello ")
    cb("tail")
    cb.flush()
    got = "".join(e[1].get("t", "") for e in ch.evts)
    assert got == "hello " + "world" * 10 + "tail"
    cb("", True)
    assert ch.evts[-1] == ("delta", {"reset": True})
    cb.flush()
    assert len(ch.evts) == 3                   # flush after reset is a no-op
