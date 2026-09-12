"""Quick Write V0.1 tests (docs/narrative-writing-product-v0.1-quick-write-spec).

Covers the 14 required tests from QUICK_WRITE_IMPLEMENTATION_TASK.md.
"""

from __future__ import annotations

import json
import time

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
    assert set(m) == {"topic", "selected_angle", "core_question",
                      "reader_end_state", "refined_thesis"}


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
    assert set(angle_ev["data"]) == {"topic", "selected_angle", "core_question",
                                     "reader_end_state", "refined_thesis"}


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


# ------------------------------------ 11. in-task param edits take effect ----

def test_generate_body_params_persist_and_reach_engine():
    spy = SpyEngine()
    c = _client(spy)
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate", json={
        "instruction": "写父亲", "immersion": "high", "explicitness": "low",
        "intensity": "low", "target_length": 1200})
    t = c.get(f"/tasks/{tid}").json()
    assert t["instruction"] == "写父亲"
    cfg = t["config"]
    assert (cfg["immersion"], cfg["explicitness"], cfg["intensity"]) == \
        ("high", "low", "low")
    assert cfg["target_length"] == 1200
    kw = spy.generate_calls[-1]
    assert kw["instruction"] == "写父亲"
    assert kw["config"]["target_length"] == 1200
    assert kw["config"]["immersion"] == "high"


def test_regenerate_body_params_persist():
    c = _client()
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate", json={})
    r = c.post(f"/tasks/{tid}/regenerate", json={
        "preserve_angle": True, "immersion": "low", "target_length": 500})
    assert r.status_code == 200, r.text
    cfg = c.get(f"/tasks/{tid}").json()["config"]
    assert (cfg["immersion"], cfg["target_length"]) == ("low", 500)


def test_generate_rejects_invalid_param_values():
    c = _client()
    tid = qw_task(c)
    assert c.post(f"/tasks/{tid}/generate",
                  json={"immersion": "extreme"}).status_code == 400
    assert c.post(f"/tasks/{tid}/generate",
                  json={"target_length": 99}).status_code == 400
    assert c.post(f"/tasks/{tid}/generate",
                  json={"target_length": "abc"}).status_code == 400


def test_generate_without_body_keeps_stored_config():
    spy = SpyEngine()
    c = _client(spy)
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate", json={})
    kw = spy.generate_calls[-1]
    assert kw["config"]["target_length"] == 900     # from creation


def test_dial_block_maps_levels_to_guidance():
    from workbench.engine.real import _dial_block
    block = _dial_block({"immersion": "high", "explicitness": "low",
                         "intensity": "medium"})
    assert "Experience settings" in block
    assert "sensory detail" in block
    assert "do not state the theme" in block.lower()
    assert block.count("\n- ") == 3
    assert _dial_block({}) == ""
    assert _dial_block({"immersion": None, "explicitness": "bogus"}) == ""


# ================= regression: T0/T1/T2 bug sweep (2026-08-31) ==============

import threading
import time

from workbench.service import _validate_target_length


# ---- T0: language gate uses discovery language, not the English seed topic ----

def test_topic_led_language_resolves_from_meaning_not_topic():
    from workbench.engine.real import resolve_language_for
    meaning = {"topic": "talk about failure", "selected_angle_id": "a1",
               "candidate_angles": [{"id": "a1", "label": "告别是重复练习的死亡"}],
               "core_question": "为什么告别让人麻木?",
               "deep_meaning": "告别揭示人对失去的防御机制",
               "reader_end_state": "读者理解自己的回避",
               "key_tensions": ["想说与不说"]}
    # English topic, Chinese discovery -> expected zh (was en -> false gate fail)
    exp = resolve_language_for({"expected_language": "auto"},
                               material="talk about failure",
                               instruction="", meaning=meaning, default="auto")
    assert exp == "zh"
    # explicit wins
    assert resolve_language_for({"expected_language": "en"}, "谈谈失败", "",
                                meaning, "auto") == "en"
    # source-grounded (no meaning): unchanged heuristic on material
    assert resolve_language_for({"expected_language": "auto"}, "an English memo",
                                "", None, "auto") == "en"


def test_gate_message_maps_reasons_to_human_zh():
    from workbench.engine.real import _gate_message
    msg = _gate_message(["language mismatch: expected en, got zh",
                         "length 1200 outside [350, 3000]"])
    assert "语言与预期不符" in msg and "篇幅" in msg
    assert _gate_message([]) == "未通过检查"
    assert _gate_message(["refusal pattern"]) == "模型拒绝了这次写作"


def test_hard_gates_allow_new_facts_skips_fidelity():
    from app.gates import hard_gates
    zh = ("2019年的冬天,他站起来说:“这么多年我们再没有提起那件事,谁也没有回头。”"
          "站台上的灯一盏一盏灭了。") * 2
    strict = hard_gates(zh, {"material": "告别", "instruction": "",
                             "target_length": 0, "expected_language": "zh"})
    assert strict["checks"]["factual_fidelity"] is False       # numerals/quote
    loose = hard_gates(zh, {"material": "告别", "instruction": "",
                            "target_length": 0, "expected_language": "zh",
                            "allow_new_facts": True})
    assert loose["checks"]["factual_fidelity"] is True
    assert loose["functional_failure"] is False


# ---- T1: SSE must not replay the previous run when a second one starts ----

def test_progress_waits_for_new_run_not_previous_replay():
    from workbench.progress import BROKER
    c = _client()
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate", json={})           # run 1 closes its channel
    old_text = c.get(f"/tasks/{tid}").json()["draft"]["working_content"][:20]

    def second_run():
        time.sleep(0.3)
        ch = BROKER.channel(tid, reset=True)
        ch.emit("stage", {"stage": "writing"})
        ch.emit("delta", {"t": "SECOND-RUN-MARKER"})
        ch.close()
    threading.Thread(target=second_run, daemon=True).start()
    with c.stream("GET", f"/tasks/{tid}/progress") as r:
        body = "".join(r.iter_text())
    assert "SECOND-RUN-MARKER" in body
    assert old_text not in body                          # no leak of run 1


def test_progress_still_replays_for_late_subscriber():
    c = _client()
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate", json={})
    with c.stream("GET", f"/tasks/{tid}/progress") as r:  # no new run coming
        body = "".join(r.iter_text())
    assert "event: delta" in body and "event: eof" in body


# ---- T1: non-EngineError must not strand status='generating' ----

class ExplodingEngine(MockWritingEngine):
    def generate(self, **kw):
        raise RuntimeError("connection reset")


def test_ungrouped_generate_error_resets_status_to_failed():
    c = _client(ExplodingEngine())
    tid = qw_task(c)
    r = c.post(f"/tasks/{tid}/generate", json={})
    assert r.status_code == 500 and r.json()["error"]["retryable"] is True
    assert c.get(f"/tasks/{tid}").json()["status"] == "failed"


# ---- T1: stale-generating escape must run before param writes touch updated_at ----

def test_stale_generating_allows_retry_despite_param_overrides():
    svc = _svc()
    c = TestClient(create_app(svc))
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate", json={})
    # force a stale 'generating' row (6 min old)
    old = "2000-01-01T00:00:00+00:00"
    svc.db.exec("UPDATE tasks SET status='generating',updated_at=? WHERE id=?",
                (old, tid))
    r = c.post(f"/tasks/{tid}/generate",
               json={"immersion": "high", "target_length": 700})
    assert r.status_code == 200                          # retry allowed


# ---- T2: regenerate/rediscover must honor the concurrency guard ----

def test_regenerate_and_rediscover_guard_concurrency():
    svc = _svc()
    c = TestClient(create_app(svc))
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate", json={})
    fresh = "2999-01-01T00:00:00+00:00"                  # future ts => age<300
    svc.db.exec("UPDATE tasks SET status='generating',updated_at=? WHERE id=?",
                (fresh, tid))
    assert c.post(f"/tasks/{tid}/regenerate",
                  json={"preserve_angle": True}).status_code == 409
    assert c.post(f"/tasks/{tid}/rediscover-angle", json={}).status_code == 409


# ---- T2: checkpoint dedupe (no version spam when content unchanged) ----

def test_checkpoint_dedupes_unchanged_content():
    c = _client()
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate", json={})
    v1 = c.post(f"/tasks/{tid}/checkpoint").json()["version_id"]
    r2 = c.post(f"/tasks/{tid}/checkpoint").json()
    assert r2.get("deduped") is True and r2["version_id"] == v1
    n = len(c.get(f"/tasks/{tid}").json()["draft"]["versions"])
    c.post(f"/tasks/{tid}/checkpoint")
    assert len(c.get(f"/tasks/{tid}").json()["draft"]["versions"]) == n


# ---- T2: target_length validated at every entry point ----

def test_target_length_validated_at_create_and_patch():
    c = _client()
    assert c.post("/tasks", json={"input_mode": "topic_only", "topic": "x",
        "config": {"target_length": 9999}}).status_code == 400
    tid = qw_task(c)
    assert c.patch(f"/tasks/{tid}", json={
        "config": {"target_length": -5}}).status_code == 400
    assert c.patch(f"/tasks/{tid}", json={
        "config": {"target_length": "many"}}).status_code == 400
    assert c.patch(f"/tasks/{tid}", json={
        "config": {"target_length": 600}}).status_code == 200


# ================= regression: T3 sweep (2026-08-31) =======================

def test_settings_view_reports_running_adapter_not_file():
    from workbench import settings as ws
    ws.save({"engine": "real"})                  # file says real...
    c = _client()                                # ...but service runs mock
    assert c.get("/settings").json()["engine"] == "mock"


def test_update_settings_rolls_back_when_engine_build_fails(monkeypatch):
    from workbench import service as svc_mod
    from workbench import settings as ws
    calls = {"n": 0}

    def flaky_engine():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("bad base_url")
        return MockWritingEngine()

    monkeypatch.setattr(svc_mod, "get_engine", flaky_engine)
    svc = Service(Database(":memory:"), engine=MockWritingEngine())
    c = TestClient(create_app(svc))
    r = c.post("/settings", json={"engine": "real"})
    assert r.status_code == 500 and r.json()["error"]["code"] == "SETTINGS_FAILED"
    assert ws.load()["engine"] == "mock"          # rolled back on disk
    assert svc.engine.name == "mock"              # and in memory


def test_generate_can_clear_instruction():
    c = _client()
    tid = qw_task(c, instruction="写父亲")
    c.post(f"/tasks/{tid}/generate", json={"instruction": ""})
    assert c.get(f"/tasks/{tid}").json()["instruction"] == ""


def test_mock_simulate_repair_emits_reset():
    eng = MockWritingEngine()
    eng.simulate_repair = True
    events = []
    res = eng.generate(material="m", instruction="i", task_type="essay",
                       config={},
                       on_delta=lambda d, r=False: events.append((d, r)))
    assert ("", True) in events                       # repair reset signal fired
    # text after the last reset reconstructs the final draft
    last = max(i for i, (d, r) in enumerate(events) if r)
    assert "".join(d for d, r in events[last + 1:] if not r) == res.text


def test_pending_patches_survive_reload_with_before_after():
    c = _client()
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate", json={})
    task = c.get(f"/tasks/{tid}").json()
    r = c.post(f"/tasks/{tid}/patch", json={
        "base_version_id": task["draft"]["current_version_id"],
        "selection": {"paragraph_start": 1, "paragraph_end": 1},
        "instruction": "shorter", "locks": {}})
    assert r.status_code == 200
    pend = c.get(f"/tasks/{tid}").json()["pending_patches"]
    assert pend and pend[0]["before"] and pend[0]["after"]
    assert pend[0]["patch_id"] == r.json()["patch_id"]


def test_test_connection_allows_empty_key_for_local_base():
    c = _client()
    r = c.post("/settings/test", json={
        "base_url": "http://127.0.0.1:9/v1", "model": "whatever", "api_key": ""})
    body = r.json()
    assert body.get("ok") is False
    assert "API key is empty" not in str(body.get("error", ""))  # connection err instead


# --------------------------- 8. stage streaming (summary + debug deltas) ----

def test_structured_call_forwards_on_delta():
    from app.config import RoleConfig
    from app.structured import structured_call

    seen = []

    class C:
        def generate_structured(self, messages, *, role, role_cfg,
                                on_delta=None):
            from app.llm_client import GenerationResult
            if on_delta:
                on_delta('{"a": ')
                on_delta('1}')
            return GenerationResult(text='{"a": 1}', model="m")

    st = structured_call(
        C(), role="architect", role_cfg=RoleConfig(model="m"),
        system_prompt="s", user_message="u",
        validator=lambda o: [], on_delta=seen.append)
    assert "".join(seen) == '{"a": 1}'
    assert st.data == {"a": 1}


def test_mock_client_structured_streams_deltas():
    from app.config import RoleConfig
    from app.llm_client import MockClient

    mc = MockClient(responses={"architect": ['{"a": 1}' + "x" * 40]})
    parts = []
    mc.generate_structured([], role="architect",
                           role_cfg=RoleConfig(model="m"),
                           on_delta=parts.append)
    assert "".join(parts) == '{"a": 1}' + "x" * 40


def test_stage_summary_events_emitted(monkeypatch):
    monkeypatch.setattr("workbench.service._debug_stream", lambda: False)
    svc = _svc()
    c = TestClient(create_app(svc))
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate", json={})
    from workbench.progress import BROKER
    kinds = [(e["kind"], e["data"]) for e in BROKER.channel(tid).events]
    sums = [d for k, d in kinds if k == "stage_summary"]
    assert any(d["stage"] == "discovery" and "找到可说的角度" in d["text"]
               for d in sums)
    assert any(d["stage"] == "structure" and d["text"].startswith("结构:")
               for d in sums)
    # summaries are human text; no raw JSON leaks into the UI events
    assert not any(k == "stage_delta" for k, _ in kinds)


def test_outline_summary_from_wir():
    from workbench.engine.real import _outline_summary
    txt = _outline_summary({"beats": [
        {"meaning_gain": "处境被看见"}, {"meaning_gain": "张力被感到"},
        {"function": {"primary": "turn"}}]})
    assert txt == "结构:处境被看见 → 张力被感到 → turn"
    assert _outline_summary({}) == "结构已确定。"


def test_stage_delta_events_only_with_debug(monkeypatch):
    monkeypatch.setattr("workbench.service._debug_stream", lambda: True)
    svc = _svc()
    c = TestClient(create_app(svc))
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate", json={})
    from workbench.progress import BROKER
    kinds = [(e["kind"], e["data"]) for e in BROKER.channel(tid).events]
    deltas = [d for k, d in kinds if k == "stage_delta"]
    assert {d["stage"] for d in deltas} == {"discovery", "structure"}


def test_review_emits_progress_and_debug_stream(monkeypatch):
    monkeypatch.setattr("workbench.service._debug_stream", lambda: True)
    svc = _svc()
    c = TestClient(create_app(svc))
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate", json={})
    r = c.post(f"/tasks/{tid}/review")
    assert r.status_code == 200
    from workbench.progress import BROKER
    evs = BROKER.channel(tid).events
    kinds = [e["kind"] for e in evs]
    assert "stage" in kinds and "stage_summary" in kinds and "done" in kinds
    st = [e["data"] for e in evs if e["kind"] == "stage"]
    assert st[-1] == {"stage": "review"}
    summ = [e["data"] for e in evs if e["kind"] == "stage_summary"]
    assert summ[-1]["stage"] == "review" and summ[-1]["text"].startswith("检查:")
    assert [e["data"]["stage"] for e in evs
            if e["kind"] == "stage_delta"] == ["review"]
    assert evs[-1]["kind"] == "done"
    assert BROKER.channel(tid).closed


def test_stream_debug_setting_roundtrip(tmp_path, monkeypatch):
    from workbench import settings as st
    monkeypatch.setattr(st, "SETTINGS_PATH", tmp_path / "settings.json")
    st.save({"stream_debug": True})
    assert st.view()["stream_debug"] is True
    st.save({"stream_debug": False})          # False must persist, not "keep"
    assert st.load()["stream_debug"] is False
    assert st.view()["stream_debug"] is False
    st.save({"stream_debug": "truthy"})
    assert st.load()["stream_debug"] is True


# --------------------------- 9. bug regression (review race, stream fallback) ----

def test_review_rejected_while_generating(monkeypatch):
    """B1: review resets the task channel; must not run during generation."""
    monkeypatch.setattr("workbench.service._debug_stream", lambda: False)
    svc = _svc()
    c = TestClient(create_app(svc))
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate", json={})
    svc.db.exec("UPDATE tasks SET status='generating' WHERE id=?", (tid,))
    r = c.post(f"/tasks/{tid}/review")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "GENERATING"


def test_structured_calls_never_stream(tmp_path, monkeypatch):
    """B2: JSON-mode calls must not use the streaming transport — gateways
    truncate streamed json_object output (reasoning models). The JSON
    constraint stays on the single non-streaming call, and on_delta
    receives the complete text in one shot."""
    import httpx
    import openai as oa
    from types import SimpleNamespace
    from app.config import RoleConfig
    from app.llm_client import OpenAIClient

    err = oa.APIStatusError(
        "stream+json unsupported",
        response=httpx.Response(400, request=httpx.Request("POST", "http://x")),
        body=None)
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if kwargs.get("stream"):
                raise err
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"a": 1}'))],
                usage=None)

    client = OpenAIClient(api_key="x", base_url="http://x")
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    parts = []
    out = client.generate_structured([], role="architect",
                                     role_cfg=RoleConfig(model="m"),
                                     on_delta=parts.append)
    assert len(calls) == 1
    assert not calls[0].get("stream")
    assert calls[0].get("response_format") == {"type": "json_object"}
    assert out.text == '{"a": 1}' and "".join(parts) == '{"a": 1}'


def test_structured_repair_resets_debug_stream():
    """B3: repair attempt must announce a reset, not concatenate onto attempt 1."""
    from app.config import RoleConfig
    from app.structured import structured_call
    from app.llm_client import GenerationResult

    seen = []

    class C:
        n = 0

        def generate_structured(self, messages, *, role, role_cfg, on_delta=None):
            C.n += 1
            text = "{bad json" if C.n == 1 else '{"a": 1}'
            if on_delta:
                on_delta(text)
            return GenerationResult(text=text, model="m")

    st = structured_call(
        C(), role="architect", role_cfg=RoleConfig(model="m"),
        system_prompt="s", user_message="u",
        validator=lambda o: [] if o == {"a": 1} else ["bad"],
        on_delta=lambda d, reset=False: seen.append((d, reset)))
    resets = [i for i, (d, r) in enumerate(seen) if r]
    assert resets and seen[resets[0]][0] == ""
    assert seen[-1] == ('{"a": 1}', False)          # attempt 2 streams after reset
    assert st.data == {"a": 1} and st.repair_used


def test_stage_stream_reset_clears_buffer():
    """B3: _stage_stream forwards reset as a flagged event with cleared buffer."""
    from workbench.service import _stage_stream
    evs = []
    cb = _stage_stream(lambda k, d: evs.append(d), "structure")
    cb("x" * 20)
    cb("", reset=True)
    cb("y" * 20)
    assert any(d.get("reset") for d in evs)
    data = [d["t"] for d in evs if not d.get("reset")]
    assert all("x" not in t for t in data[1:])       # buffer cleared at reset


def test_settings_stream_debug_string_false(tmp_path, monkeypatch):
    """B6: "false"/"0"/"no" strings must not coerce to True; "" keeps current."""
    from workbench import settings as st
    monkeypatch.setattr(st, "SETTINGS_PATH", tmp_path / "settings.json")
    st.save({"stream_debug": True})
    st.save({"stream_debug": "false"})
    assert st.load()["stream_debug"] is False
    st.save({"stream_debug": "0"})
    assert st.load()["stream_debug"] is False
    st.save({"stream_debug": True})
    st.save({"stream_debug": ""})
    assert st.load()["stream_debug"] is True         # empty keeps current


def test_mock_discovery_no_delta_on_failure():
    """B5: failed discovery must not emit debug tokens."""
    seen = []
    with pytest.raises(DiscoveryFailed):
        MockWritingEngine().discover_meaning(
            topic="   ", writing_mode="deep_narrative", angle_mode="auto",
            custom_angle="", avoid=[], config={}, on_delta=seen.append)
    assert seen == []


def test_generate_rejected_while_reviewing(monkeypatch):
    """B1 (reverse direction): an in-flight review owns the task channel."""
    monkeypatch.setattr("workbench.service._debug_stream", lambda: False)
    svc = _svc()
    c = TestClient(create_app(svc))
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate", json={})
    svc._reviewing.add(tid)                       # simulate mid-review
    r = c.post(f"/tasks/{tid}/generate", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "REVIEWING"
    r = c.post(f"/tasks/{tid}/regenerate", json={"preserve_angle": True})
    assert r.status_code == 409                    # regenerate guarded too
    r = c.post(f"/tasks/{tid}/rediscover-angle", json={})
    assert r.status_code == 409                    # rediscover guarded too
    svc._reviewing.discard(tid)
    assert c.post(f"/tasks/{tid}/generate", json={}).status_code == 200


def test_concurrent_reviews_rejected_and_flag_released(monkeypatch):
    """Two simultaneous reviews: the second gets 409; flag always released."""
    import threading
    monkeypatch.setattr("workbench.service._debug_stream", lambda: False)

    gate = threading.Event()

    class BlockingReviewEngine(MockWritingEngine):
        def review(self, **kw):
            gate.wait(5)
            return super().review(**kw)

    svc = _svc(BlockingReviewEngine())
    c = TestClient(create_app(svc))
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate", json={})

    first = threading.Thread(target=lambda: c.post(f"/tasks/{tid}/review"))
    first.start()
    for _ in range(100):
        if tid in svc._reviewing:
            break
        time.sleep(0.02)
    assert tid in svc._reviewing
    r = c.post(f"/tasks/{tid}/review")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "REVIEWING"
    gate.set()
    first.join(6)
    assert not svc._reviewing                      # released after completion


# ---------------------------------- 15. thinking chain (meaning pipeline v2) ----

def _chain_mock():
    return MockWritingEngine().discover_meaning(
        topic="谈谈失败", writing_mode="deep_narrative", angle_mode="auto",
        custom_angle="", avoid=[], config={})


def test_thinking_chain_fields_required_and_produced():
    d = _chain_mock()
    for f in ("crack", "strongest_counterexample", "boundary", "refined_thesis"):
        assert d.get(f), f"missing chain field {f}"
    assert meaning_schema.validate_meaning(d) == []


def test_thinking_chain_fields_are_schema_required():
    import copy
    d = _chain_mock()
    for f in ("crack", "strongest_counterexample", "boundary", "refined_thesis"):
        broken = copy.deepcopy(d)
        broken.pop(f)
        errs = meaning_schema.validate_meaning(broken)
        assert any(f in e for e in errs), f"{f} not enforced"


def test_refined_thesis_must_migrate_frame():
    d = _chain_mock()
    d["refined_thesis"] = d["common_reading"]          # no frame migration
    errs = meaning_schema.validate_meaning(d)
    assert any("frame migration" in e for e in errs)


def test_wir_handoff_carries_chain_fields():
    d = _chain_mock()
    block = meaning_schema.meaning_to_wir_block(d)
    for f in ("refined_thesis", "strongest_counterexample", "boundary"):
        assert block.get(f)


def test_progression_contract_in_wir_instruction():
    from workbench.engine.real import _compose_topic_instruction
    instruction = _compose_topic_instruction("", _chain_mock())
    assert "Progression contract" in instruction
    assert "Refined thesis" in instruction
    assert "Strongest counterexample to face:" in instruction
    assert "Boundary of the thesis:" in instruction
    assert "counterexample" in instruction and "boundary" in instruction


def test_product_summary_includes_refined_thesis():
    d = _chain_mock()
    s = meaning_schema.product_safe_summary(d)
    assert s["refined_thesis"] == d["refined_thesis"]
    assert "crack" not in s          # internal chain step, not exposed


def test_generate_payload_can_reset_target_length_and_dials():
    c = _client()
    tid = qw_task(c)
    c.patch(f"/tasks/{tid}", json={"config": {"immersion": "high",
                                              "target_length": 500}})
    body = {"immersion": None, "target_length": None}   # UI sends explicit reset
    r = c.post(f"/tasks/{tid}/generate?skip=1", json=body)
    assert r.status_code in (200, 500)   # mock engine may fail transport; overrides applied first
    t = c.get(f"/tasks/{tid}").json()["config"]
    assert t["immersion"] is None and t["target_length"] is None
