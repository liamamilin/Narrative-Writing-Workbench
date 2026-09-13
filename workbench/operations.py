"""Bounded, user-triggered operations for one local server process.

SQL owns the task reservation; ContextVar pins the adapter across all stages.
Completed stage events survive restart; token previews remain in memory.
"""

from contextvars import ContextVar
from dataclasses import asdict
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import time

from app.llm_client import CALL_OBSERVER
from .db import new_id
from .progress import BROKER

PROCESS_ID = new_id("process")
CURRENT = ContextVar("writing_operation", default=None)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def engine_snapshot(engine):
    cfg = getattr(engine, "config", None)
    prompt_dir = getattr(cfg, "prompts_dir", Path(__file__).resolve().parent.parent / "prompts")
    snapshot = {"engine": engine.name, "roles": {}, "prompts": {}}
    if cfg:
        snapshot["roles"] = {name: asdict(role) for name, role in cfg.roles.items()}
        snapshot["expected_language"] = cfg.expected_language
        snapshot["thresholds"] = asdict(cfg.thresholds)
        # Store only a fingerprint of the actual endpoint, never credentials.
        client = getattr(getattr(engine, "client", None), "_client", None)
        endpoint = str(getattr(client, "base_url", "") or os.environ.get(cfg.base_url_env, ""))
        snapshot["endpoint_hash"] = digest(endpoint)
    for file in sorted(Path(prompt_dir).rglob("*.md")):
        snapshot["prompts"][str(file.relative_to(prompt_dir))] = hashlib.sha256(file.read_bytes()).hexdigest()
    return snapshot


class Operation:
    def __init__(self, db, task_id, kind, engine):
        self.db, self.task_id, self.kind, self.engine = db, task_id, kind, engine
        self.id = new_id("op")
        self.snapshot = engine_snapshot(engine)
        self.started = time.monotonic()
        self.channel = None
        self._usage = {"known_calls": 0, "unknown_calls": 0,
                       "input_tokens": 0, "output_tokens": 0,
                       "latency_seconds": 0.0}

    def bind_inputs(self, inputs):
        self.db.exec("UPDATE writing_operations SET input_fingerprint=?,snapshot_json=? WHERE id=?",
                     (digest(inputs), json.dumps({"engine": self.snapshot, "inputs": inputs}, ensure_ascii=False), self.id))

    def event(self, event):
        if event["kind"] in ("delta", "stage_delta"):
            return
        elapsed = round((time.monotonic() - self.started) * 1000)
        with self.db.transaction() as tx:
            tx.exec("INSERT INTO operation_events(operation_id,seq,kind,data_json,elapsed_ms,created_at) VALUES(?,?,?,?,?,?)",
                    (self.id, event["seq"], event["kind"], json.dumps(event["data"], ensure_ascii=False), elapsed, timestamp()))
            if event["kind"] == "stage":
                tx.exec("UPDATE writing_operations SET stage=? WHERE id=?",
                        (event["data"].get("stage"), self.id))

    def record(self, category, name, status="completed", data=None):
        elapsed = round((time.monotonic() - self.started) * 1000)
        self.db.exec(
            "INSERT INTO operation_records(id,operation_id,category,name,status,data_json,elapsed_ms,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (new_id("record"), self.id, category, name, status,
             json.dumps(data or {}, ensure_ascii=False), elapsed, timestamp()))

    def record_call(self, call):
        names = {
            "meaning_discovery": "meaning_discovery",
            "thesis_judge": "meaning_review",
            "architect": "structure",
            "writer": "writing",
            "critic": "review",
            "evidence_check": "evidence_check",
            "patcher": "revision",
        }
        usage = call.get("usage")
        if usage is None:
            self._usage["unknown_calls"] += 1
        else:
            self._usage["known_calls"] += 1
            self._usage["input_tokens"] += usage["input_tokens"]
            self._usage["output_tokens"] += usage["output_tokens"]
        latency = call.get("latency_seconds")
        if latency is not None:
            self._usage["latency_seconds"] += latency
        self.record("model_call", names.get(call["role"], "model_call"),
                    call["status"], {
                        "kind": call["kind"], "model": call.get("model"),
                        "usage": usage, "latency_seconds": latency})
        summary = {**self._usage,
                   "latency_seconds": round(self._usage["latency_seconds"], 6),
                   "complete": self._usage["unknown_calls"] == 0}
        self.db.exec("UPDATE writing_operations SET usage_json=? WHERE id=?",
                     (json.dumps(summary), self.id))


def tracked(kind):
    def decorate(fn):
        @wraps(fn)
        def wrapped(service, tid, *args, **kwargs):
            from .service import ApiError
            op = Operation(service.db, tid, kind, service.engine)
            with service.db.transaction() as tx:
                task = tx.q1("SELECT status FROM tasks WHERE id=?", (tid,))
                if not task:
                    raise ApiError("NOT_FOUND", "Task not found.", 404)
                running = tx.q1("SELECT kind FROM writing_operations WHERE task_id=? AND status='running'", (tid,))
                if running or task["status"] == "generating":
                    code = "REVIEWING" if running and running["kind"] == "review" else "GENERATING"
                    raise ApiError(code, "任务仍在执行，请等待完成。", 409)
                previous = tx.q1("SELECT id FROM writing_operations WHERE task_id=? AND status IN ('failed','interrupted') ORDER BY rowid DESC LIMIT 1", (tid,))
                payload = (args[0] if args and isinstance(args[0], dict) else kwargs.get("payload")) or {}
                tx.exec("INSERT INTO writing_operations(id,task_id,kind,process_id,status,stage,started_at,snapshot_json,retry_of) VALUES(?,?,?,?,?,?,?,?,?)",
                        (op.id, tid, kind, PROCESS_ID, "running", "queued", timestamp(),
                         json.dumps({"engine": op.snapshot}), previous["id"] if previous and payload.get("resume") else None))
            op.channel = BROKER.channel(tid, reset=True, operation_id=op.id, on_event=op.event)
            token = CURRENT.set(op)
            call_token = CALL_OBSERVER.set(op.record_call)
            try:
                result = fn(service, tid, *args, **kwargs)
                service.db.exec("UPDATE writing_operations SET status='succeeded',finished_at=?,elapsed_ms=?,result_json=? WHERE id=?",
                                (timestamp(), round((time.monotonic() - op.started) * 1000),
                                 json.dumps({k: v for k, v in result.items() if k in ("version_id", "draft_id", "id")}), op.id))
                return {**result, "operation_id": op.id}
            except BaseException as exc:
                code = getattr(exc, "code", "INTERNAL")
                with service.db.transaction() as tx:
                    tx.exec("UPDATE writing_operations SET status='failed',finished_at=?,elapsed_ms=?,error_code=? WHERE id=?",
                            (timestamp(), round((time.monotonic() - op.started) * 1000), code, op.id))
                    # Validation failures before execution keep the prior task state.
                    tx.exec("UPDATE tasks SET status='failed',updated_at=? WHERE id=? AND status='generating'", (timestamp(), tid))
                if not op.channel.closed:
                    op.channel.emit("error", {"message": getattr(exc, "message", "本次运行失败，请重试。"), "code": code})
                raise
            finally:
                op.channel.close()
                CALL_OBSERVER.reset(call_token)
                CURRENT.reset(token)
        return wrapped
    return decorate


def recover_interrupted(db):
    """Called on startup under the single-server constraint; never reruns work."""
    with db.transaction() as tx:
        tx.exec("UPDATE writing_operations SET status='interrupted',finished_at=?,error_code='PROCESS_INTERRUPTED' WHERE status='running' AND process_id<>?",
                (timestamp(), PROCESS_ID))
        tx.exec("UPDATE tasks SET status='failed',updated_at=? WHERE status='generating' AND NOT EXISTS (SELECT 1 FROM writing_operations o WHERE o.task_id=tasks.id AND o.status='running')",
                (timestamp(),))
