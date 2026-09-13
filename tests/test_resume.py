"""Resume-at-last-successful-node tests.

Failure retry resumes from the last successful node (discovery / WIR plan)
instead of restarting the whole pipeline. Nodes:
- N1 meaning discovery (topic_only): always reused (topic immutable);
- N2 WIR plan: reused only when the inputs fingerprint matches;
- N3 writer: rerun (single LLM call, no token-level resume).
"""

from __future__ import annotations

from conftest import RevisionClient as TestClient

from workbench.api import create_app
from workbench.db import Database
from workbench.engine.mock import MockWritingEngine
from workbench.service import Service


class FailWriterEngine(MockWritingEngine):
    """Fails AFTER the plan node (writer stage) — the resumable failure."""

    def __init__(self):
        super().__init__()
        self.fail_writer = True
        self.generate_calls = []

    def generate(self, **kw):
        self.generate_calls.append(kw)
        return super().generate(**kw)


class SpyEngine(MockWritingEngine):
    def __init__(self):
        super().__init__()
        self.generate_calls = []

    def generate(self, **kw):
        self.generate_calls.append(kw)
        return super().generate(**kw)


def _svc(engine):
    return Service(Database(":memory:"), engine=engine)


def _client(engine):
    return TestClient(create_app(_svc(engine)))


def qw_task(c, **over):
    body = {"input_mode": "topic_only", "topic": "谈谈失败",
            "writing_mode": "deep_narrative", "angle_mode": "auto",
            "config": {"expected_language": "zh", "target_length": 900}}
    body.update(over)
    r = c.post("/tasks", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def src_task(c):
    r = c.post("/tasks", json={
        "input_mode": "source_grounded", "type": "essay",
        "instruction": "分析这个现象",
        "material": "很多人明知道结局还是被故事抓住。",
        "config": {"expected_language": "zh"},
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_topic_only_failure_retry_resumes_from_plan():
    eng = FailWriterEngine()
    db = Database(":memory:")
    c = TestClient(create_app(Service(db, engine=eng)))
    tid = qw_task(c)
    r = c.post(f"/tasks/{tid}/generate")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "GENERATION_FAILED"
    # plan node persisted despite the writer failure
    plan = db.q1("SELECT * FROM engine_plans WHERE task_id=?", (tid,))
    assert plan is not None and plan["inputs_json"]
    assert len(db.q("SELECT * FROM meaning_discoveries WHERE task_id=?", (tid,))) == 1
    # retry with resume: discovery NOT rerun, plan reused, draft lands
    eng.fail_writer = False
    r2 = c.post(f"/tasks/{tid}/generate", json={"resume": True})
    assert r2.status_code == 200
    assert len(db.q("SELECT * FROM meaning_discoveries WHERE task_id=?", (tid,))) == 1
    assert eng.generate_calls[0]["plan"] is None      # first run: architect
    assert eng.generate_calls[-1]["plan"] is not None  # resume: plan reused
    t = c.get(f"/tasks/{tid}").json()
    assert t["status"] == "ready" and t["draft"]


def test_retry_without_resume_flag_restarts_full_pipeline():
    eng = FailWriterEngine()
    db = Database(":memory:")
    c = TestClient(create_app(Service(db, engine=eng)))
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate")
    eng.fail_writer = False
    c.post(f"/tasks/{tid}/generate")     # no resume flag -> fresh everything
    assert len(db.q("SELECT * FROM meaning_discoveries WHERE task_id=?", (tid,))) == 2
    assert eng.generate_calls[-1]["plan"] is None


def test_resume_plan_invalidated_when_instruction_changes():
    eng = FailWriterEngine()
    db = Database(":memory:")
    c = TestClient(create_app(Service(db, engine=eng)))
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate")
    eng.fail_writer = False
    c.patch(f"/tasks/{tid}", json={"instruction": "改一版意图"})
    r = c.post(f"/tasks/{tid}/generate", json={"resume": True})
    assert r.status_code == 200
    # discovery still reused (topic immutable), plan invalidated
    assert len(db.q("SELECT * FROM meaning_discoveries WHERE task_id=?", (tid,))) == 1
    assert eng.generate_calls[-1]["plan"] is None


def test_source_grounded_failure_retry_resumes_from_plan():
    eng = FailWriterEngine()
    db = Database(":memory:")
    c = TestClient(create_app(Service(db, engine=eng)))
    tid = src_task(c)
    r = c.post(f"/tasks/{tid}/generate")
    assert r.status_code == 500
    assert db.q1("SELECT * FROM engine_plans WHERE task_id=?", (tid,)) is not None
    eng.fail_writer = False
    r2 = c.post(f"/tasks/{tid}/generate", json={"resume": True})
    assert r2.status_code == 200
    assert eng.generate_calls[-1]["plan"] is not None


def test_regenerate_same_angle_reuses_plan():
    spy = SpyEngine()
    db = Database(":memory:")
    c = TestClient(create_app(Service(db, engine=spy)))
    tid = qw_task(c)
    c.post(f"/tasks/{tid}/generate")
    r = c.post(f"/tasks/{tid}/regenerate", json={"preserve_angle": True})
    assert r.status_code == 200
    assert spy.generate_calls[-1]["plan"] is not None   # writer-only rewrite
