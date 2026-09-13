"""Lifecycle tests use gates and clock offsets, never a five-minute wait."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import RoleConfig
from app.llm_client import CALL_OBSERVER, MockClient, OpenAIClient
from workbench.api import create_app
from workbench.db import Database, SCHEMA_VERSION
from workbench.engine.mock import MockWritingEngine
from workbench.operations import PROCESS_ID
from workbench.service import Service


def task(svc):
    return svc.create_task({"input_mode": "topic_only", "topic": "等待"})["id"]


class Blocked(MockWritingEngine):
    def __init__(self):
        super().__init__()
        self.entered, self.release = threading.Event(), threading.Event()
        self.write_calls = 0

    def discover_meaning(self, **kw):
        self.entered.set()
        assert self.release.wait(10)
        return super().discover_meaning(**kw)

    def generate(self, **kw):
        self.write_calls += 1
        return super().generate(**kw)


def test_old_timestamp_does_not_allow_overlapping_operations():
    engine = Blocked()
    svc = Service(Database(":memory:"), engine)
    tid = task(svc)
    with ThreadPoolExecutor() as pool:
        first = pool.submit(svc.generate, tid)
        assert engine.entered.wait(5)
        try:
            svc.db.exec("UPDATE tasks SET updated_at='2000-01-01T00:00:00+00:00' WHERE id=?", (tid,))
            c = TestClient(create_app(svc))
            for endpoint in ("generate", "regenerate", "rediscover-angle", "review"):
                assert c.post(f"/tasks/{tid}/{endpoint}").status_code == 409
            assert len(svc.db.q("SELECT * FROM writing_operations")) == 1
        finally:
            engine.release.set()
        assert first.result(timeout=5)["version_id"]


def test_hot_swap_during_discovery_keeps_original_adapter():
    engine = Blocked()
    svc = Service(Database(":memory:"), engine)
    tid = task(svc)
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(svc.generate, tid)
        assert engine.entered.wait(5)
        replacement = MockWritingEngine()
        replacement.fail_generate = True
        svc.engine = replacement
        engine.release.set()
        result = pending.result(timeout=5)
    assert engine.write_calls == 1
    op = svc.operation_detail(tid, result["operation_id"])
    assert op["status"] == "succeeded" and op["elapsed_ms"] >= 0
    assert op["result"]["version_id"] == result["version_id"]


def test_restart_marks_previous_process_interrupted_without_model_calls(tmp_path):
    path = tmp_path / "restart.db"
    svc = Service(Database(path), MockWritingEngine())
    tid = task(svc)
    svc.db.exec("INSERT INTO writing_operations(id,task_id,kind,process_id,status,started_at) VALUES('old',?,'generate','previous-process','running','yesterday')", (tid,))
    svc.db.exec("UPDATE tasks SET status='generating' WHERE id=?", (tid,))
    svc.db.conn.close()
    restarted = Service(Database(path), MockWritingEngine())
    assert restarted.get_task(tid)["status"] == "failed"
    op = restarted.operation_detail(tid, "old")
    assert op["status"] == "interrupted" and op["error_code"] == "PROCESS_INTERRUPTED"
    assert not restarted.db.q("SELECT * FROM drafts")
    result = restarted.generate(tid, {"resume": True})
    assert restarted.operation_detail(tid, result["operation_id"])["retry_of"] == "old"
    assert restarted.operation_detail(tid, "old")["status"] == "interrupted"


def test_one_process_service_rebuild_does_not_interrupt_live_work():
    engine = Blocked()
    db = Database(":memory:")
    svc = Service(db, engine)
    tid = task(svc)
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(svc.generate, tid)
        assert engine.entered.wait(5)
        try:
            Service(db, MockWritingEngine())
            op = svc._operation_view(tid)
            assert op["status"] == "running"
        finally:
            engine.release.set()
        pending.result(timeout=5)


def test_operation_history_and_resume_config_are_bound(monkeypatch):
    engine = MockWritingEngine()
    engine.fail_writer = True
    svc = Service(Database(":memory:"), engine)
    tid = task(svc)
    c = TestClient(create_app(svc))
    assert c.post(f"/tasks/{tid}/generate").status_code == 500
    old = svc._operation_view(tid)["id"]
    engine.fail_writer = False
    # Model identity change invalidates both meaning and plan reuse.
    engine.name = "mock-v2"
    result = c.post(f"/tasks/{tid}/generate", json={"resume": True}).json()
    assert len(svc.db.q("SELECT * FROM meaning_discoveries")) == 2
    assert len(svc.db.q("SELECT * FROM engine_plans")) == 2
    assert svc.operation_detail(tid, old)["status"] == "failed"
    op = svc.operation_detail(tid, result["operation_id"])
    assert op["retry_of"] == old
    assert all(e["kind"] not in ("delta", "stage_delta") for e in op["events"])
    stored = svc.db.q1("SELECT * FROM writing_operations WHERE id=?", (result["operation_id"],))
    assert stored["usage_json"] is None
    assert "api_key" not in stored["snapshot_json"]


def test_specific_operation_sse_never_replays_new_run():
    svc = Service(Database(":memory:"), MockWritingEngine())
    tid = task(svc)
    first = svc.generate(tid)
    second = svc.generate(tid, {"expected_revision": first["revision"]})
    c = TestClient(create_app(svc))
    old = c.get(f"/tasks/{tid}/progress", params={"operation_id": first["operation_id"]})
    assert first["operation_id"] in old.text
    assert second["operation_id"] not in old.text
    assert 'event: eof' in old.text
    assert c.get(f"/tasks/{tid}/operations/missing").status_code == 404


def test_single_server_lease_is_released(tmp_path):
    import pytest
    from workbench.instance import server_lease
    path = tmp_path / "lease.db"
    with server_lease(path):
        with pytest.raises(RuntimeError, match="已有"):
            with server_lease(path):
                pass
    with server_lease(path):
        pass


def test_migration_failure_rolls_back_and_consistent_backup_restores(tmp_path, monkeypatch):
    import sqlite3
    import pytest
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE preserved(value TEXT)")
        conn.execute("INSERT INTO preserved VALUES('original')")
    original = Database._migrate
    def fail(self):
        original(self)
        raise RuntimeError("injected migration failure")
    monkeypatch.setattr(Database, "_migrate", fail)
    with pytest.raises(RuntimeError, match="injected"):
        Database(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("preserved",)]
    backup = next(tmp_path.glob("*.pre-v6-*.sqlite3"))
    restored = tmp_path / "restored.db"
    with sqlite3.connect(backup) as source, sqlite3.connect(restored) as target:
        source.backup(target)
        assert target.execute("SELECT * FROM preserved").fetchall() == [("original",)]
        assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    monkeypatch.setattr(Database, "_migrate", original)
    upgraded = Database(path)
    assert upgraded.q1("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    assert upgraded.q1("SELECT * FROM preserved")["value"] == "original"


class InstrumentedEngine(MockWritingEngine):
    def __init__(self):
        super().__init__()
        self.client = MockClient({"writer": ["observed output"]})

    def generate(self, **kwargs):
        self.client.generate_text(
            [{"role": "user", "content": "only metadata may be recorded"}],
            role="writer", role_cfg=RoleConfig(model="observed-model"))
        return super().generate(**kwargs)


def test_operation_records_safe_model_metadata_and_known_usage():
    svc = Service(Database(":memory:"), InstrumentedEngine())
    tid = task(svc)
    result = svc.generate(tid)
    operation = svc.operation_detail(tid, result["operation_id"])
    assert operation["usage"]["complete"] is True
    assert operation["usage"]["known_calls"] == 1
    assert operation["usage"]["input_tokens"] > 0
    call = next(r for r in operation["records"] if r["category"] == "model_call")
    assert call["name"] == "writing"
    assert call["data"]["model"] == "mock"
    serialized = json.dumps(operation, ensure_ascii=False)
    assert "only metadata may be recorded" not in serialized
    assert "observed output" not in serialized
    assert "api_key" not in serialized


def test_streaming_provider_usage_is_explicitly_unknown():
    client = object.__new__(OpenAIClient)
    client._create = lambda *args, **kwargs: iter([
        SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content="piece"))])])
    records = []
    token = CALL_OBSERVER.set(records.append)
    try:
        result = client.generate_text(
            [{"role": "user", "content": "secret input"}], role="writer",
            role_cfg=RoleConfig(model="streamed"), on_delta=lambda _: None)
    finally:
        CALL_OBSERVER.reset(token)
    assert result.usage_known is False
    assert records == [{
        "role": "writer", "kind": "text", "status": "completed",
        "model": "streamed", "latency_seconds": result.latency_seconds,
        "usage": None}]


def test_failed_provider_call_records_model_without_request_content():
    client = object.__new__(OpenAIClient)
    client._create = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("provider unavailable"))
    records = []
    token = CALL_OBSERVER.set(records.append)
    try:
        import pytest
        with pytest.raises(RuntimeError, match="provider unavailable"):
            client.generate_structured(
                [{"role": "user", "content": "private request"}],
                role="critic", role_cfg=RoleConfig(model="failed-model"))
    finally:
        CALL_OBSERVER.reset(token)
    assert len(records) == 1
    assert records[0]["status"] == "failed"
    assert records[0]["model"] == "failed-model"
    assert records[0]["usage"] is None
    assert "private request" not in json.dumps(records)
