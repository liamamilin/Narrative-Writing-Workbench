"""Workbench product services: CRUD + hard invariants (product/06).

Golden rules enforced here:
- AI proposes, user accepts: a ProposedPatch never mutates the Draft.
- Accept creates a Version; Reject creates nothing.
- Generation/patch failure leaves existing content untouched.
- Restore is itself a new version (reversible).
- Autosave writes working_content only; it never creates versions.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from . import meaning_schema
from . import settings as settings_mod
from .db import Database, new_id
from .engine import (EngineError, GenerationFailed, LockConflict,
                     get_engine)
from .progress import BROKER

log = logging.getLogger("workbench.service")

_TAXONOMY_PATH = Path(__file__).resolve().parent / "taxonomy.json"


@lru_cache(maxsize=1)
def _load_taxonomy() -> dict:
    """Two-level topic taxonomy (static, versioned in-repo)."""
    return json.loads(_TAXONOMY_PATH.read_text(encoding="utf-8"))

TASK_TYPES = {"fiction_scene", "narrative_analysis", "character_analysis",
              "essay", "emotional_retelling", "free_writing"}
EXPERIENCE_LEVELS = {"low", "medium", "high"}
INPUT_MODES = {"topic_only", "source_grounded", "draft_revision"}
WRITING_MODES = {"deep_narrative", "clear_essay", "fiction", "free_writing"}
ANGLE_MODES = {"auto", "custom"}
# writing_mode -> engine task type (engine task types are closed; map onto them)
_WRITING_MODE_TO_TYPE = {
    "deep_narrative": "essay",
    "clear_essay": "essay",
    "fiction": "fiction_scene",
    "free_writing": "free_writing",
}

# Lightweight fact-heavy topic heuristic (product/18). Conservative by
# design: false positives only surface a dismissible warning; false
# negatives are acceptable in V0.1.
_FACT_PATTERNS = [
    r"\d{3,4}\s*年", r"\d+(?:\.\d+)?\s*(?:%|百分之|亿|万人|万人)",
    r"人口", r"经济", r"GDP", r"股价", r"裁员", r"破产", r"选举", r"战争",
    r"政策", r"疫情", r"灭亡", r"崩盘", r"获奖", r"上市公司",
    r"(?:公司|集团|政府|部门|团队)s*", r"为什么.{0,12}(?:灭亡|失败|下跌|崩溃|裁员)",
    r"\b(?:economy|election|company|stock|GDP|population|war|policy|data)\b",
]
_FACT_RE = [re.compile(p, re.IGNORECASE) for p in _FACT_PATTERNS]


def detect_fact_heavy(topic: str) -> bool:
    t = (topic or "").strip()
    return any(rx.search(t) for rx in _FACT_RE)


def _delta_stream(ch):
    """Batch engine text deltas into SSE 'delta' events.

    Small batches (>=8 chars) keep the token-by-token feel; a 0.3s age
    flush prevents a partial buffer from stalling when the model pauses
    (e.g. between paragraphs).
    """
    buf = []
    size = [0]
    last = [time.monotonic()]

    def cb(delta, reset=False):
        if reset:
            buf.clear()
            size[0] = 0
            ch.emit("delta", {"reset": True})
            return
        buf.append(delta)
        size[0] += len(delta)
        if size[0] >= 8 or (time.monotonic() - last[0]) >= 0.3:
            ch.emit("delta", {"t": "".join(buf)})
            buf.clear()
            size[0] = 0
            last[0] = time.monotonic()

    def flush():
        if buf:
            ch.emit("delta", {"t": "".join(buf)})
            buf.clear()
            size[0] = 0

    cb.flush = flush
    return cb


def _stage_stream(emit, stage: str, min_chars: int = 16):
    """Batch intermediate-stage deltas into SSE 'stage_delta' events.

    Only wired when settings.stream_debug is on; the UI renders these as a
    raw-token debug preview (the JSON is engine-internal, not user copy).
    """
    buf = []
    size = [0]
    last = [time.monotonic()]

    def cb(delta, reset=False):
        if reset:
            buf.clear()
            size[0] = 0
            emit("stage_delta", {"stage": stage, "t": "", "reset": True})
            return
        buf.append(delta)
        size[0] += len(delta)
        if size[0] >= min_chars or (time.monotonic() - last[0]) >= 0.3:
            emit("stage_delta", {"stage": stage, "t": "".join(buf)})
            buf.clear()
            size[0] = 0
            last[0] = time.monotonic()

    def flush():
        if buf:
            emit("stage_delta", {"stage": stage, "t": "".join(buf)})
            buf.clear()
            size[0] = 0

    cb.flush = flush
    return cb


def _debug_stream() -> bool:
    return bool(settings_mod.load().get("stream_debug", False))


_REVIEW_DIM_ZH = {"progression": "推进", "meaning_density": "意义密度",
                  "immersion": "沉浸", "restraint": "克制",
                  "coherence": "连贯"}
_REVIEW_LABEL_ZH = {"strong": "强", "good": "良",
                    "needs_attention": "需加强"}


def _review_summary_text(payload: dict) -> str:
    parts = [f"{_REVIEW_DIM_ZH.get(k, k)}:{_REVIEW_LABEL_ZH.get(v, v)}"
             for k, v in (payload.get("summary") or {}).items()]
    n = len(payload.get("issues") or [])
    return ("检查:" + " · ".join(parts)
            + (f";{n} 个可改进点" if n else ";未发现明显问题"))


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400,
                 retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.status, self.retryable = (
            code, message, status, retryable)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_target_length(value) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 5000:
        raise ApiError("VALIDATION", "target_length must be an integer 100-5000.")


def paragraphs(content: str) -> list[str]:
    return content.split("\n\n")


def paragraph_span(content: str, start: int, end: int) -> tuple[int, int]:
    """Char span of 1-based inclusive paragraph range [start, end]."""
    paras = paragraphs(content)
    if not (1 <= start <= end <= len(paras)) or start > len(paras):
        raise ApiError("INVALID_SELECTION", "Selection is outside the draft.")
    offset = 0
    for i, p in enumerate(paras, 1):
        if i == start:
            char_start = offset
        offset += len(p) + 2  # the "\n\n" separator
    if end > len(paras):
        raise ApiError("INVALID_SELECTION", "Selection is outside the draft.")
    char_end = offset - 2  # exclude trailing separator of last selected para
    # recompute precisely
    offset = 0
    for i, p in enumerate(paras, 1):
        if i == end:
            char_end = offset + len(p)
        offset += len(p) + 2
    return char_start, char_end


class Service:
    def __init__(self, db: Database | None = None, engine=None):
        self.db = db or Database()
        self.engine = engine or get_engine()
        # In-flight reviews per task (in-memory: dies with the process, so a
        # crash can never wedge it; generation uses the DB stale flag instead).
        self._reviewing: set[str] = set()
        self._reviewing_lock = threading.Lock()

    # ------------------------------------------------------------- project ----

    def create_project(self, name: str, description: str = "") -> dict:
        if not name or not name.strip():
            raise ApiError("VALIDATION", "Project name is required.")
        pid = new_id("proj")
        ts = now()
        self.db.exec(
            "INSERT INTO projects VALUES(?,?,?,?,?)",
            (pid, name.strip(), description.strip(), ts, ts))
        return self.get_project(pid)

    def list_projects(self) -> list[dict]:
        return self.db.q("SELECT * FROM projects ORDER BY updated_at DESC")

    def get_project(self, pid: str) -> dict:
        row = self.db.q1("SELECT * FROM projects WHERE id=?", (pid,))
        if not row:
            raise ApiError("NOT_FOUND", "Project not found.", 404)
        return row

    def project_detail(self, pid: str) -> dict:
        project = self.get_project(pid)
        project["tasks"] = self.db.q(
            "SELECT * FROM tasks WHERE project_id=? ORDER BY updated_at DESC",
            (pid,))
        project["sources"] = self.db.q(
            "SELECT id,title,type,project_id,updated_at FROM sources "
            "WHERE project_id=? ORDER BY updated_at DESC", (pid,))
        return project

    # ------------------------------------------------------------- source ----

    def create_source(self, project_id: str | None, title: str, type_: str,
                      content: str, metadata: dict | None = None) -> dict:
        if type_ not in ("pasted_text", "uploaded_file", "note"):
            raise ApiError("VALIDATION", "Unknown source type.")
        if not content.strip():
            raise ApiError("VALIDATION", "Source content is empty.")
        if project_id and not self.db.q1("SELECT id FROM projects WHERE id=?",
                                         (project_id,)):
            raise ApiError("NOT_FOUND", "Project not found.", 404)
        sid = new_id("src")
        ts = now()
        self.db.exec("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",
                     (sid, project_id, title or "Untitled", type_, content,
                      json.dumps(metadata or {}, ensure_ascii=False), ts, ts))
        return self.db.q1("SELECT * FROM sources WHERE id=?", (sid,))

    # --------------------------------------------------------------- task ----

    def create_task(self, payload: dict) -> dict:
        input_mode = payload.get("input_mode") or "source_grounded"
        if input_mode not in INPUT_MODES:
            raise ApiError("VALIDATION", "Unknown input_mode.")
        topic = (payload.get("topic") or "").strip()
        writing_mode = payload.get("writing_mode") or ""
        angle_mode = payload.get("angle_mode") or "auto"
        custom_angle = (payload.get("custom_angle") or "").strip()
        instruction = (payload.get("instruction") or "").strip()
        material = (payload.get("material") or "").strip()

        if input_mode == "topic_only":
            if not topic:
                raise ApiError("VALIDATION", "Enter a topic to write about.")
            if writing_mode and writing_mode not in WRITING_MODES:
                raise ApiError("VALIDATION", "Unknown writing_mode.")
            if angle_mode not in ANGLE_MODES:
                raise ApiError("VALIDATION", "angle_mode must be auto or custom.")
            if angle_mode == "custom" and not custom_angle:
                raise ApiError("VALIDATION", "Provide the angle you have in mind.")
            if not writing_mode:
                writing_mode = "deep_narrative"
            ttype = _WRITING_MODE_TO_TYPE[writing_mode]
        else:
            ttype = payload.get("type")
            if ttype not in TASK_TYPES:
                raise ApiError("VALIDATION", "Choose a task type.")
            if not instruction and not material:
                raise ApiError("VALIDATION",
                               "Add an instruction or some material to start.")
        project_id = payload.get("project_id")
        if project_id:
            self.get_project(project_id)
        cfg = payload.get("config") or {}
        for key in ("immersion", "explicitness", "intensity"):
            value = cfg.get(key)
            if value and value not in EXPERIENCE_LEVELS:
                raise ApiError("VALIDATION", f"Invalid {value} for {key}.")
        _validate_target_length(cfg.get("target_length"))
        expected_language = cfg.get("expected_language")
        if expected_language not in (None, "auto", "zh", "en"):
            raise ApiError("VALIDATION", "expected_language must be zh, en or auto.")
        tid = new_id("task")
        ts = now()
        self.db.exec(
            "INSERT INTO tasks(id,project_id,type,title,instruction,status,"
            "expected_language,created_at,updated_at,input_mode,topic,"
            "writing_mode,angle_mode,custom_angle) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tid, project_id, ttype, (payload.get("title") or "").strip(),
             instruction, "draft", expected_language or "auto", ts, ts,
             input_mode, topic, writing_mode, angle_mode, custom_angle))
        locks = dict(cfg.get("locks") or {})
        if input_mode == "topic_only":
            locks.setdefault("core_meaning", True)  # Preserve Core Meaning default ON
        self.db.exec("INSERT INTO writing_configs VALUES(?,?,?,?,?,?,?)",
                     (tid, cfg.get("immersion"), cfg.get("explicitness"),
                      cfg.get("intensity"), cfg.get("target_length"),
                      json.dumps(locks, ensure_ascii=False),
                      json.dumps(cfg.get("constraints") or {}, ensure_ascii=False)))
        if material:
            src = self.create_source(project_id, "Task material",
                                     "pasted_text", material)
            self.db.exec("INSERT INTO task_sources VALUES(?,?,?)",
                         (tid, src["id"], "primary"))
        for sid in payload.get("source_ids") or []:
            if not self.db.q1("SELECT id FROM sources WHERE id=?", (sid,)):
                raise ApiError("NOT_FOUND", f"Source {sid} not found.", 404)
            self.db.exec("INSERT OR IGNORE INTO task_sources VALUES(?,?,?)",
                         (tid, sid, "context"))
        return self.get_task(tid)

    def get_task(self, tid: str) -> dict:
        row = self.db.q1("SELECT * FROM tasks WHERE id=?", (tid,))
        if not row:
            raise ApiError("NOT_FOUND", "Task not found.", 404)
        row["config"] = self.db.q1("SELECT * FROM writing_configs WHERE task_id=?",
                                   (tid,)) or {}
        row["config"]["locks"] = json.loads(row["config"].get("locks_json") or "{}")
        row["config"]["constraints"] = json.loads(
            row["config"].get("constraints_json") or "{}")
        row["sources"] = self.db.q(
            "SELECT s.id,s.title,s.type,s.content,ts.role FROM sources s "
            "JOIN task_sources ts ON ts.source_id=s.id "
            "WHERE ts.task_id=? ORDER BY ts.role", (tid,))
        return row

    def task_detail(self, tid: str) -> dict:
        task = self.get_task(tid)
        draft = self.db.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
        task["draft"] = None
        task["pending_patches"] = []
        if draft:
            draft["versions"] = self.db.q(
                "SELECT id,source_type,instruction,created_at,parent_version_id"
                " FROM versions WHERE draft_id=? ORDER BY created_at, rowid", (draft["id"],))
            task["draft"] = draft
            task["pending_patches"] = [
                {"patch_id": p["id"], "instruction": p["instruction"],
                 "before": p["before_text"] or "", "after": p["after_text"] or "",
                 "selection": json.loads(p["selection_json"])}
                for p in self.db.q(
                    "SELECT * FROM proposed_patches WHERE draft_id=? AND status='proposed'",
                    (draft["id"],))]
        # fact-heavy topic warning: only while still topic_only with no sources
        if task.get("input_mode") == "topic_only" and not task["sources"]:
            task["factuality_warning"] = detect_fact_heavy(task.get("topic", ""))
        else:
            task["factuality_warning"] = False
        return task

    def _config_dict(self, task: dict) -> dict:
        cfg = task["config"]
        return {
            "expected_language": task["expected_language"],
            "immersion": cfg.get("immersion"),
            "explicitness": cfg.get("explicitness"),
            "intensity": cfg.get("intensity"),
            "target_length": cfg.get("target_length"),
            "locks": cfg.get("locks") or {},
            "constraints": cfg.get("constraints") or {},
        }

    def _apply_param_overrides(self, task: dict, payload: dict) -> dict:
        """Persist intent/experience/length edits sent with a generate call.

        The Goal panel edits live in the DOM; without this they never reach
        the DB and regeneration silently reuses the last-saved config. Only
        keys actually present in the payload are written (partial updates).
        """
        tid = task["id"]
        patch: dict = {}
        if "instruction" in payload:
            instr = (payload["instruction"] or "").strip()
            if instr != (task["instruction"] or ""):   # explicit "" clears too
                patch["instruction"] = instr
        cfg: dict = {}
        for key in ("immersion", "explicitness", "intensity"):
            if key in payload and payload[key]:
                if payload[key] not in EXPERIENCE_LEVELS:
                    raise ApiError("VALIDATION", f"Invalid {key} value.")
                cfg[key] = payload[key]
        if "target_length" in payload and payload["target_length"] is not None:
            try:
                tl = int(payload["target_length"])
            except (TypeError, ValueError):
                raise ApiError("VALIDATION", "target_length must be an integer.")
            _validate_target_length(tl)
            cfg["target_length"] = tl
        if cfg:
            patch["config"] = cfg
        if patch:
            return self.update_task(tid, patch)
        return task

    def _material(self, task: dict) -> str:
        parts = [s["content"] for s in task["sources"]
                 if s["role"] in ("primary", "context")]
        return "\n\n".join(parts)

    def update_task(self, tid: str, payload: dict) -> dict:
        task = self.get_task(tid)
        ts = now()
        sets, args = [], []
        if "instruction" in payload:
            sets.append("instruction=?"); args.append(payload["instruction"])
        if "title" in payload:
            sets.append("title=?"); args.append(payload["title"])
        if "status" in payload:
            if payload["status"] not in ("draft", "ready", "failed", "done"):
                raise ApiError("VALIDATION", "Unknown task status.")
            sets.append("status=?"); args.append(payload["status"])
        if "expected_language" in payload:
            if payload["expected_language"] not in ("auto", "zh", "en"):
                raise ApiError("VALIDATION", "expected_language must be zh/en/auto.")
            sets.append("expected_language=?"); args.append(payload["expected_language"])
        sets.append("updated_at=?"); args.append(ts)
        self.db.exec(f"UPDATE tasks SET {','.join(sets)} WHERE id=?",
                     (*args, tid))
        cfg = payload.get("config")
        if cfg:
            cur = task["config"]
            merged = {
                "immersion": cfg.get("immersion", cur.get("immersion")),
                "explicitness": cfg.get("explicitness", cur.get("explicitness")),
                "intensity": cfg.get("intensity", cur.get("intensity")),
                "target_length": cfg.get("target_length", cur.get("target_length")),
                "locks": cfg.get("locks", cur.get("locks")),
                "constraints": cfg.get("constraints", cur.get("constraints")),
            }
            for key in ("immersion", "explicitness", "intensity"):
                if merged[key] and merged[key] not in EXPERIENCE_LEVELS:
                    raise ApiError("VALIDATION", f"Invalid {key} value.")
            _validate_target_length(merged["target_length"])
            self.db.exec(
                "UPDATE writing_configs SET immersion=?,explicitness=?,intensity=?"
                ",target_length=?,locks_json=?,constraints_json=? WHERE task_id=?",
                (merged["immersion"], merged["explicitness"], merged["intensity"],
                 merged["target_length"],
                 json.dumps(merged["locks"] or {}, ensure_ascii=False),
                 json.dumps(merged["constraints"] or {}, ensure_ascii=False), tid))
        return self.get_task(tid)

    def add_task_source(self, tid: str, title: str, content: str) -> dict:
        task = self.get_task(tid)
        if not content.strip():
            raise ApiError("VALIDATION", "Source content is empty.")
        src = self.create_source(task.get("project_id"), title or "Note",
                                 "pasted_text", content)
        self.db.exec("INSERT INTO task_sources VALUES(?,?,?)",
                     (tid, src["id"], "context"))
        # topic_only → source_grounded transition (persisted; product/18)
        if task.get("input_mode") == "topic_only":
            self._record_mode_transition(tid, "topic_only", "source_grounded")
            self.db.exec("UPDATE tasks SET input_mode='source_grounded',"
                         "updated_at=? WHERE id=?", (now(), tid))
        return src

    def _record_mode_transition(self, tid, frm, to):
        cfg = self.db.q1("SELECT * FROM writing_configs WHERE task_id=?", (tid,))
        constraints = json.loads((cfg or {}).get("constraints_json") or "{}")
        history = constraints.setdefault("mode_transitions", [])
        history.append({"from": frm, "to": to, "at": now()})
        self.db.exec("UPDATE writing_configs SET constraints_json=? WHERE task_id=?",
                     (json.dumps(constraints, ensure_ascii=False), tid))

    # ---------------------------------------------------------- generate ----

    def _guard_not_generating(self, task: dict) -> None:
        """Reject concurrent generation; allow retry past a 5-min stale flag.

        Must run BEFORE any param persistence: update_task refreshes
        updated_at, which would reset the staleness clock forever.
        """
        if task["status"] != "generating":
            return
        age = (datetime.now(timezone.utc)
               - datetime.fromisoformat(task["updated_at"])).total_seconds()
        if age < 300:
            raise ApiError("GENERATING", "Generation is already running.", 409)
        # stale generating flag (client/server died): allow retry

    def _guard_not_reviewing(self, tid: str) -> None:
        """Reject generation starts while a review holds the task channel."""
        with self._reviewing_lock:
            if tid in self._reviewing:
                raise ApiError("REVIEWING",
                               "A review is running. Wait for it to finish.",
                               409)

    def generate(self, tid: str, payload: dict | None = None) -> dict:
        self._guard_not_generating(self.get_task(tid))
        self._guard_not_reviewing(tid)
        task = self._apply_param_overrides(self.get_task(tid), payload or {})
        ch = BROKER.channel(tid, reset=True)
        ch.emit("stage", {"stage": "queued"})
        material = self._material(task)
        if task.get("input_mode") != "topic_only":
            if not material and not task["instruction"]:
                ch.close()
                raise ApiError("VALIDATION", "Add material or an intent first.")
            try:
                return self._generate_with(task, meaning=None)
            finally:
                ch.close()
        # Quick Write golden path: Meaning Discovery -> Angle -> WIR -> Writer
        try:
            discovery = self.discover(task, emit=ch.emit)
            if not material:
                material = task["topic"]
            return self._generate_with(task, meaning=discovery, material=material)
        finally:
            ch.close()

    def discover(self, task: dict, avoid: list[str] | None = None,
                 emit=None) -> dict:
        """Run Meaning Discovery, validate, persist (append-only lineage)."""
        tid = task["id"]
        avoid = avoid if avoid is not None else self._past_angle_labels(tid)
        self.db.exec("UPDATE tasks SET status='generating',updated_at=? WHERE id=?",
                     (now(), tid))
        stage_cb = _stage_stream(emit, "discovery") if (emit and _debug_stream()) else None
        try:
            data = self.engine.discover_meaning(
                topic=task["topic"], writing_mode=task.get("writing_mode") or "deep_narrative",
                angle_mode=task.get("angle_mode") or "auto",
                custom_angle=task.get("custom_angle") or "",
                avoid=avoid, config=self._config_dict(task), emit=emit,
                on_delta=stage_cb)
        except EngineError as exc:
            self._persist_discovery(tid, task["topic"], None, "failed",
                                    {"error": str(exc)})
            self.db.exec("UPDATE tasks SET status='failed',updated_at=? WHERE id=?",
                         (now(), tid))
            if emit:
                emit("error", {"message": str(exc) or "No angle found."})
            raise ApiError("DISCOVERY_FAILED",
                           str(exc) or "We couldn't find a strong angle. Please retry.",
                           500, retryable=True) from exc
        except Exception as exc:            # transport/ungrouped: never stick
            log.exception("ungrouped discovery error for %s", tid)
            self._persist_discovery(tid, task["topic"], None, "failed",
                                    {"error": f"{type(exc).__name__}: {exc}"})
            self.db.exec("UPDATE tasks SET status='failed',updated_at=? WHERE id=?",
                         (now(), tid))
            if emit:
                emit("error", {"message": "Discovery failed."})
            detail = str(exc) or type(exc).__name__
            raise ApiError("DISCOVERY_FAILED",
                           f"寻找角度失败: {detail}\n"
                           "可能原因: 模型名称错误、API 地址不可达、或 API Key 无效。\n"
                           "请在 Settings 中检查 Model 名称是否正确，"
                           "以及 Base URL 和 API Key 是否匹配。",
                           500, retryable=True) from exc
        finally:
            if stage_cb:
                stage_cb.flush()
        errors = meaning_schema.validate_meaning(data)
        if errors:
            self._persist_discovery(tid, task["topic"], None, "failed",
                                    {"error": errors[:3]})
            self.db.exec("UPDATE tasks SET status='failed',updated_at=? WHERE id=?",
                         (now(), tid))
            if emit:
                emit("error", {"message": "No strong angle this time. Please retry."})
            raise ApiError("DISCOVERY_FAILED",
                           "We couldn't find a strong angle. Please retry.",
                           500, retryable=True)
        if emit:
            emit("angle", meaning_schema.product_safe_summary(data))
            sel = meaning_schema.selected_angle(data).get("label", "")
            cq = (data.get("core_question") or "").strip()
            emit("stage_summary", {
                "stage": "discovery",
                "text": (f"找到可说的角度:{sel}" if sel else "找到可说的角度")
                        + (f" —— 核心问题:{cq}" if cq else "")})
        return self._persist_discovery(tid, task["topic"],
                                       data.get("selected_angle_id"), "ready", data)

    def _persist_discovery(self, tid, topic, selected_id, status, data) -> dict:
        mid = new_id("mean")
        self.db.exec(
            "INSERT INTO meaning_discoveries(id,task_id,topic,selected_angle_id,"
            "status,data_json,created_at) VALUES(?,?,?,?,?,?,?)",
            (mid, tid, topic, selected_id, status,
             json.dumps(data, ensure_ascii=False), now()))
        row = self.db.q1("SELECT * FROM meaning_discoveries WHERE id=?", (mid,))
        row["data"] = data if status == "ready" else None
        return row

    def _past_angle_labels(self, tid: str) -> list[str]:
        labels = []
        for r in self.db.q("SELECT data_json FROM meaning_discoveries "
                           "WHERE task_id=? AND status='ready'", (tid,)):
            try:
                d = json.loads(r["data_json"])
            except json.JSONDecodeError:
                continue
            for c in d.get("candidate_angles", []):
                if c.get("id") == d.get("selected_angle_id") and c.get("label"):
                    labels.append(c["label"])
        return labels

    def _latest_discovery(self, tid: str) -> dict | None:
        row = self.db.q1("SELECT * FROM meaning_discoveries WHERE task_id=?"
                         " AND status='ready'"
                         " ORDER BY created_at DESC, rowid DESC LIMIT 1", (tid,))
        if not row:
            return None
        row["data"] = json.loads(row["data_json"])
        return row

    def _generate_with(self, task: dict, meaning: dict | None,
                       material: str | None = None) -> dict:
        tid = task["id"]
        ch = BROKER.channel(tid)
        emit = ch.emit
        stream = _delta_stream(ch)
        struct_cb = (_stage_stream(emit, "structure")
                     if _debug_stream() else None)
        if material is None:
            material = self._material(task)
        self.db.exec("UPDATE tasks SET status='generating',updated_at=? WHERE id=?",
                     (now(), tid))
        try:
            result = self.engine.generate(
                material=material, instruction=task["instruction"],
                task_type=task["type"], config=self._config_dict(task),
                meaning=(meaning or {}).get("data") if meaning else None,
                emit=emit, on_delta=stream, on_struct_delta=struct_cb)
        except EngineError as exc:
            # failure safety: previous draft/versions untouched
            self.db.exec("UPDATE tasks SET status='failed',updated_at=? WHERE id=?",
                         (now(), tid))
            emit("error", {"message": str(exc) or "Generation failed."})
            raise ApiError("GENERATION_FAILED",
                           str(exc) or "The draft could not be generated correctly.",
                           500, retryable=True) from exc
        except Exception as exc:            # transport errors, poisoned config…
            log.exception("ungrouped generation error for %s", tid)
            self.db.exec("UPDATE tasks SET status='failed',updated_at=? WHERE id=?",
                         (now(), tid))
            emit("error", {"message": "Generation failed."})
            detail = str(exc) or type(exc).__name__
            raise ApiError("GENERATION_FAILED",
                           f"生成失败: {detail}\n"
                           "可能原因: 模型名称错误、API 地址不可达、或 API Key 无效。\n"
                           "请在 Settings 中检查 Model 名称是否正确，"
                           "以及 Base URL 和 API Key 是否匹配。",
                           500, retryable=True) from exc
        finally:
            if struct_cb:
                struct_cb.flush()
        ts = now()
        plan_id = new_id("plan")
        self.db.exec(
            "INSERT INTO engine_plans(id,task_id,schema_version,data_json,"
            "created_at,meaning_id) VALUES(?,?,?,?,?,?)",
            (plan_id, tid, "1", json.dumps(result.plan, ensure_ascii=False), ts,
             (meaning or {}).get("id")))
        draft = self.db.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
        if not draft:
            did = new_id("draft")
            self.db.exec("INSERT INTO drafts VALUES(?,?,?,?,?)",
                         (did, tid, None, "", ts))
            draft = self.db.q1("SELECT * FROM drafts WHERE id=?", (did,))
        vid = new_id("ver")
        self.db.exec("INSERT INTO versions VALUES(?,?,?,?,?,?,?)",
                     (vid, draft["id"], draft["current_version_id"],
                      result.text, "generation", None, ts))
        self.db.exec("UPDATE drafts SET current_version_id=?,working_content=?,updated_at=?"
                     " WHERE id=?", (vid, result.text, ts, draft["id"]))
        self.db.exec("UPDATE tasks SET status='ready',updated_at=? WHERE id=?", (ts, tid))
        stream.flush()
        emit("done", {"version_id": vid})
        return {"task_id": tid, "draft_id": draft["id"], "version_id": vid,
                "content": result.text, "status": "completed"}

    # ------------------------------------------------------------ review ----

    def review(self, tid: str) -> dict:
        task = self.get_task(tid)
        # Review resets the task's SSE channel; running it mid-generation would
        # orphan the live stream. Serialize against in-flight generation.
        self._guard_not_generating(task)
        draft = self.db.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
        if not draft or not draft["working_content"].strip():
            raise ApiError("NO_DRAFT", "Generate a draft before review.", 409)
        with self._reviewing_lock:
            if tid in self._reviewing:
                raise ApiError("REVIEWING", "Review is already running.", 409)
            self._reviewing.add(tid)
        try:
            return self._review_inner(tid, task, draft)
        finally:
            with self._reviewing_lock:
                self._reviewing.discard(tid)

    def _review_inner(self, tid: str, task: dict, draft: dict) -> dict:
        plan = self._latest_plan(tid)
        ch = BROKER.channel(tid, reset=True)
        rev_cb = _stage_stream(ch.emit, "review") if _debug_stream() else None
        ch.emit("stage", {"stage": "review"})
        try:
            try:
                payload = self.engine.review(
                    content=draft["working_content"], material=self._material(task),
                    instruction=task["instruction"], plan=plan,
                    config=self._config_dict(task), on_delta=rev_cb)
            except EngineError as exc:
                ch.emit("error", {"message": str(exc) or "Review failed."})
                raise ApiError("REVIEW_FAILED", str(exc), 500, retryable=True) from exc
            except Exception as exc:
                log.exception("ungrouped review error for %s", tid)
                ch.emit("error", {"message": "Review failed."})
                raise ApiError("REVIEW_FAILED",
                               f"检查失败:{type(exc).__name__} — 请重试。",
                               500, retryable=True) from exc
            rid = new_id("rev")
            self.db.exec("INSERT INTO reviews VALUES(?,?,?,?,?,?)",
                         (rid, draft["id"], draft["current_version_id"],
                          json.dumps(payload["summary"], ensure_ascii=False),
                          json.dumps(payload["issues"], ensure_ascii=False), now()))
            ch.emit("stage_summary", {"stage": "review",
                                      "text": _review_summary_text(payload)})
            ch.emit("done", {"review_id": rid})
            return payload
        finally:
            if rev_cb:
                rev_cb.flush()
            ch.close()

    def _latest_plan(self, tid: str) -> dict | None:
        row = self.db.q1("SELECT data_json FROM engine_plans WHERE task_id=?"
                         " ORDER BY created_at DESC LIMIT 1", (tid,))
        return json.loads(row["data_json"]) if row else None

    # ------------------------------------------------------------- patch ----

    def propose_patch(self, tid: str, payload: dict) -> dict:
        base_version_id = payload.get("base_version_id")
        selection = payload.get("selection") or {}
        instruction = (payload.get("instruction") or "").strip()
        if not instruction:
            raise ApiError("VALIDATION", "Tell me how to revise the passage.")
        ps, pe = selection.get("paragraph_start"), selection.get("paragraph_end")
        if not (isinstance(ps, int) and isinstance(pe, int) and 1 <= ps <= pe):
            raise ApiError("VALIDATION", "Select a passage first.")
        task = self.get_task(tid)
        draft = self.db.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
        if not draft:
            raise ApiError("NO_DRAFT", "Generate a draft first.", 409)
        if base_version_id and base_version_id != draft["current_version_id"]:
            raise ApiError("STALE_BASE",
                           "The draft changed since this revision was requested.",
                           409, retryable=True)
        content = draft["working_content"]
        char_start, char_end = paragraph_span(content, ps, pe)
        before_text = content[char_start:char_end]
        locks = payload.get("locks") or task["config"].get("locks") or {}
        try:
            after_text = self.engine.patch(
                content=content, before_text=before_text,
                instruction=instruction, locks=locks,
                config=self._config_dict(task))
        except LockConflict as exc:
            # fail safely: no patch row, draft untouched
            raise ApiError("LOCK_CONFLICT", str(exc), 422, retryable=True) from exc
        except EngineError as exc:
            raise ApiError("PATCH_FAILED", str(exc), 500, retryable=True) from exc
        pid = new_id("patch")
        ts = now()
        selection_json = json.dumps(
            {"paragraph_start": ps, "paragraph_end": pe,
             "char_start": char_start, "char_end": char_end},
            ensure_ascii=False)
        self.db.exec(
            "INSERT INTO proposed_patches VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (pid, draft["id"], draft["current_version_id"], selection_json,
             instruction, before_text, after_text, "proposed",
             json.dumps(locks, ensure_ascii=False), None, ts))
        return {"patch_id": pid, "before": before_text, "after": after_text,
                "status": "proposed"}

    def accept_patch(self, patch_id: str) -> dict:
        patch = self.db.q1("SELECT * FROM proposed_patches WHERE id=?", (patch_id,))
        if not patch:
            raise ApiError("NOT_FOUND", "Patch not found.", 404)
        if patch["status"] != "proposed":
            raise ApiError("STALE_PATCH", "This patch was already resolved.", 409)
        draft = self.db.q1("SELECT * FROM drafts WHERE id=?", (patch["draft_id"],))
        if draft["current_version_id"] != patch["base_version_id"]:
            raise ApiError("STALE_BASE",
                           "The draft changed; review the patch against the new version.",
                           409, retryable=True)
        sel = json.loads(patch["selection_json"])
        content = draft["working_content"]
        # integrity: the recorded slice must still match byte-for-byte
        if content[sel["char_start"]:sel["char_end"]] != patch["before_text"]:
            raise ApiError("STALE_BASE", "The selected passage changed.", 409,
                           retryable=True)
        new_content = (content[:sel["char_start"]] + patch["after_text"]
                       + content[sel["char_end"]:])
        ts = now()
        vid = new_id("ver")
        self.db.exec("INSERT INTO versions VALUES(?,?,?,?,?,?,?)",
                     (vid, draft["id"], draft["current_version_id"], new_content,
                      "patch", patch["instruction"], ts))
        self.db.exec("UPDATE drafts SET current_version_id=?,working_content=?,updated_at=?"
                     " WHERE id=?", (vid, new_content, ts, draft["id"]))
        self.db.exec("UPDATE proposed_patches SET status='accepted' WHERE id=?",
                     (patch_id,))
        return {"patch_id": patch_id, "version_id": vid, "status": "accepted",
                "content": new_content}

    def reject_patch(self, patch_id: str) -> dict:
        patch = self.db.q1("SELECT * FROM proposed_patches WHERE id=?", (patch_id,))
        if not patch:
            raise ApiError("NOT_FOUND", "Patch not found.", 404)
        if patch["status"] != "proposed":
            raise ApiError("STALE_PATCH", "This patch was already resolved.", 409)
        self.db.exec("UPDATE proposed_patches SET status='rejected' WHERE id=?",
                     (patch_id,))
        # invariant: reject never touches the draft
        return {"patch_id": patch_id, "status": "rejected"}

    # ---------------------------------------------------------- versions ----

    def list_versions(self, draft_id: str) -> list[dict]:
        rows = self.db.q(
            "SELECT id,draft_id,parent_version_id,source_type,instruction,created_at"
            " FROM versions WHERE draft_id=? ORDER BY created_at, rowid", (draft_id,))
        for r in rows:
            r["origin"] = _ORIGINS.get(r["source_type"], r["source_type"])
        return rows

    def get_version(self, version_id: str) -> dict:
        row = self.db.q1("SELECT * FROM versions WHERE id=?", (version_id,))
        if not row:
            raise ApiError("NOT_FOUND", "Version not found.", 404)
        row["origin"] = _ORIGINS.get(row["source_type"], row["source_type"])
        return row

    def restore_version(self, version_id: str) -> dict:
        version = self.get_version(version_id)
        draft = self.db.q1("SELECT * FROM drafts WHERE id=?", (version["draft_id"],))
        ts = now()
        rid = new_id("ver")
        # restore is itself a new version: fully reversible
        self.db.exec("INSERT INTO versions VALUES(?,?,?,?,?,?,?)",
                     (rid, draft["id"], draft["current_version_id"],
                      version["content"], "restore", None, ts))
        self.db.exec("UPDATE drafts SET current_version_id=?,working_content=?,updated_at=?"
                     " WHERE id=?", (rid, version["content"], ts, draft["id"]))
        return {"version_id": rid, "restored_from": version_id, "content": version["content"]}

    def checkpoint(self, tid: str) -> dict:
        task = self.get_task(tid)
        draft = self.db.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
        if not draft:
            raise ApiError("NO_DRAFT", "Generate a draft first.", 409)
        if draft["current_version_id"]:
            cur = self.db.q1("SELECT content FROM versions WHERE id=?",
                             (draft["current_version_id"],))
            if cur and cur["content"] == draft["working_content"]:
                return {"version_id": draft["current_version_id"], "deduped": True}
        ts = now()
        vid = new_id("ver")
        self.db.exec("INSERT INTO versions VALUES(?,?,?,?,?,?,?)",
                     (vid, draft["id"], draft["current_version_id"],
                      draft["working_content"], "manual_checkpoint", None, ts))
        self.db.exec("UPDATE drafts SET current_version_id=?,updated_at=? WHERE id=?",
                     (vid, ts, draft["id"]))
        return {"version_id": vid}

    # --------------------------------------------------------- autosave ----

    def autosave(self, draft_id: str, working_content: str) -> dict:
        draft = self.db.q1("SELECT * FROM drafts WHERE id=?", (draft_id,))
        if not draft:
            raise ApiError("NOT_FOUND", "Draft not found.", 404)
        self.db.exec("UPDATE drafts SET working_content=?,updated_at=? WHERE id=?",
                     (working_content, now(), draft_id))
        # note: no version created (autosave must not spam history)
        return {"draft_id": draft_id, "saved_at": now()}

    # ------------------------------------------------------ retry paths ----

    def rediscover_angle(self, tid: str, payload: dict | None = None) -> dict:
        """Try Another Angle: rerun Meaning Discovery/selection, then generate.

        Distinct code path from regenerate(): discovery runs again with an
        avoid-list of every previously selected angle.
        """
        self._guard_not_generating(self.get_task(tid))
        self._guard_not_reviewing(tid)
        task = self._apply_param_overrides(self.get_task(tid), payload or {})
        if task.get("input_mode") != "topic_only":
            raise ApiError("VALIDATION",
                           "Angle retry is only for idea-based tasks.", 409)
        avoid = self._past_angle_labels(tid)
        ch = BROKER.channel(tid, reset=True)
        ch.emit("stage", {"stage": "queued"})
        try:
            discovery = self.discover(task, avoid=avoid, emit=ch.emit)
            material = self._material(task) or task["topic"]
            return self._generate_with(task, meaning=discovery, material=material)
        finally:
            ch.close()

    def regenerate(self, tid: str, payload: dict) -> dict:
        """Rewrite Same Angle: preserve the selected meaning, rerun downstream."""
        self._guard_not_generating(self.get_task(tid))
        self._guard_not_reviewing(tid)
        task = self._apply_param_overrides(self.get_task(tid), payload)
        if task.get("input_mode") != "topic_only":
            raise ApiError("VALIDATION",
                           "This rewrite applies only to idea-based tasks.", 409)
        preserve = payload.get("preserve_angle", True)
        if preserve is not True:
            raise ApiError("VALIDATION", "preserve_angle must be true.")
        discovery = self._latest_discovery(tid)
        if not discovery:
            raise ApiError("NO_MEANING",
                           "Generate once first so an angle can be preserved.", 409)
        ch = BROKER.channel(tid, reset=True)
        ch.emit("stage", {"stage": "queued"})
        ch.emit("angle", meaning_schema.product_safe_summary(discovery["data"]))
        try:
            material = self._material(task) or task["topic"]
            return self._generate_with(task, meaning=discovery, material=material)
        finally:
            ch.close()

    def suggest_instruction(self, tid: str, payload: dict | None = None) -> dict:
        """Draft/sharpen the task's Intent via the model.

        AI proposes, user accepts: this never writes the field. It only
        returns a suggestion the frontend may fill in on the user's click.
        """
        task = self.get_task(tid)
        material = self._material(task) or task.get("topic") or ""
        if not material and not task["instruction"]:
            raise ApiError("VALIDATION",
                           "先给素材或话题,我才能帮你提一个意图.", 409)
        config = self._config_dict(task)
        meaning = self._latest_discovery(tid)
        avoid = [str(x).strip() for x in (payload or {}).get("avoid") or []
                 if str(x).strip()]
        try:
            suggestion = self.engine.suggest_instruction(
                material=material, topic=task.get("topic") or "",
                task_type=task["type"], instruction=task["instruction"],
                config=config, language=config.get("expected_language") or "auto",
                meaning=(meaning or {}).get("data") if meaning else None,
                avoid=avoid)
        except EngineError as exc:
            raise ApiError("INTENT_SUGGEST_FAILED",
                           str(exc) or "Could not draft an instruction. Please retry.",
                           500, retryable=True) from exc
        except Exception as exc:            # transport errors, poisoned config…
            log.exception("intent suggestion failed for %s", tid)
            detail = str(exc) or type(exc).__name__
            raise ApiError("INTENT_SUGGEST_FAILED",
                           f"意图建议失败: {detail}\n"
                           "可能原因: 模型名称错误、API 地址不可达、或 API Key 无效。\n"
                           "请在 Settings 中检查 Model 名称是否正确，"
                           "以及 Base URL 和 API Key 是否匹配。",
                           500, retryable=True) from exc
        return {"suggestion": suggestion}

    def taxonomy(self) -> dict:
        """Two-level topic taxonomy for the Quick Write topic picker."""
        return _load_taxonomy()

    def suggest_topics(self, payload: dict | None = None) -> dict:
        """Propose discussable topics. AI proposes, user accepts: nothing is
        persisted; the frontend only fills the topic input on a click."""
        payload = payload or {}
        taxonomy = _load_taxonomy()
        domain = str(payload.get("domain") or "").strip() or None
        # "sub" kept as a legacy alias for tension (v1 taxonomy param name).
        tension = str(payload.get("tension")
                      or payload.get("sub") or "").strip() or None
        known_domains = {d["id"] for d in taxonomy["domains"]}
        known_tensions = {t["id"] for t in taxonomy["tensions"]}
        if domain is not None and domain not in known_domains:
            raise ApiError("VALIDATION", f"unknown domain: {domain}")
        if tension is not None and tension not in known_tensions:
            raise ApiError("VALIDATION", f"unknown tension: {tension}")
        avoid = [str(x).strip() for x in payload.get("avoid") or []
                 if str(x).strip()]
        try:
            data = self.engine.suggest_topics(domain=domain, tension=tension,
                                              avoid=avoid, config=None)
        except EngineError as exc:
            raise ApiError("TOPIC_SUGGEST_FAILED",
                           str(exc) or "Could not suggest topics. Please retry.",
                           500, retryable=True) from exc
        except Exception as exc:            # transport errors, poisoned config…
            log.exception("topic suggestion failed")
            raise ApiError("TOPIC_SUGGEST_FAILED",
                           f"话题建议失败:{type(exc).__name__} — 请重试。",
                           500, retryable=True) from exc
        return {"topics": list(data.get("topics") or [])}

    def meaning_summary(self, tid: str) -> dict:
        """Product-safe view of the latest discovery (4 fields; no reasoning)."""
        self.get_task(tid)  # 404 guard
        discovery = self._latest_discovery(tid)
        if not discovery:
            raise ApiError("NO_MEANING", "No meaning has been discovered yet.", 404)
        return meaning_schema.product_safe_summary(discovery["data"])

    # --------------------------------------------------------- settings ----

    def settings_view(self) -> dict:
        from .settings import view
        return {**view(), "engine": self.engine.name}

    def update_settings(self, payload: dict) -> dict:
        from .settings import SETTINGS_PATH, apply_env, load, save, view
        allowed = ("engine", "api_key", "base_url", "model",
                   "timeout_seconds", "writer_temperature", "stream_debug")
        patch = {k: payload[k] for k in allowed if k in payload}
        if patch.get("engine") not in (None, "mock", "real"):
            raise ApiError("VALIDATION", "engine must be mock or real.")
        previous = load()
        saved = save(patch)
        apply_env(saved)
        try:
            self.engine = get_engine()      # hot-swap the adapter
        except Exception as exc:
            # never leave env/file switched to a config the server can't run
            SETTINGS_PATH.write_text(
                json.dumps({**previous, "engine": "mock"}, ensure_ascii=False),
                encoding="utf-8")
            apply_env(load())
            self.engine = get_engine()
            raise ApiError("SETTINGS_FAILED",
                           f"引擎切换失败(已回退到 mock):{exc}", 500) from exc
        return {**view(saved), "engine": self.engine.name}

    def list_providers(self) -> list[dict]:
        return list(settings_mod.PROVIDERS)

    def fetch_models(self, payload: dict) -> dict:
        """Query GET {base}/models (OpenAI-compatible) for the model dropdown."""
        import os as _os
        from .settings import PROVIDERS
        s = settings_mod.load()
        base = (payload.get("base_url") or "").strip() or s.get("base_url") \
            or _os.environ.get("OPENAI_BASE_URL") or ""
        key = (payload.get("api_key") or "").strip() or s.get("api_key") \
            or _os.environ.get("OPENAI_API_KEY") or ""
        if not base:
            return {"ok": False, "error": "Base URL is empty."}
        if not key and any(p["base_url"] and base.rstrip("/").startswith(p["base_url"].rstrip("/"))
                           for p in PROVIDERS if not p["needs_key"]):
            key = settings_mod.LOCAL_KEY_PLACEHOLDER
        if not key:
            return {"ok": False, "error": "API key is empty."}
        try:
            from openai import OpenAI
            cli = OpenAI(api_key=key, base_url=base, timeout=15,
                         default_headers=_session_headers())
            data = cli.models.list()
            models = sorted(getattr(m, "id", str(m)) for m in (data.data or []))
            return {"ok": True, "models": models}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300]}

    def test_connection(self, payload: dict) -> dict:
        import os as _os
        import time as _time
        from .settings import load
        s = load()
        key = (payload.get("api_key") or "").strip() or s.get("api_key") \
            or _os.environ.get("OPENAI_API_KEY") or ""
        base = (payload.get("base_url") or "").strip() or s.get("base_url") \
            or _os.environ.get("OPENAI_BASE_URL") or ""
        model = (payload.get("model") or "").strip() or s.get("model") or ""
        if not model:
            from .settings import _model_from_config_yaml
            model = _model_from_config_yaml() or ""
        if not key:
            # local servers (Ollama/LM Studio) accept any non-empty key;
            # match fetch_models' behavior — the UI says "可留空" for them
            from .settings import PROVIDERS, LOCAL_KEY_PLACEHOLDER
            b = base.rstrip("/")
            is_local = ("127.0.0.1" in b or "localhost" in b
                        or any(p["base_url"] and
                               b.startswith(p["base_url"].rstrip("/"))
                               for p in PROVIDERS if not p["needs_key"]))
            if is_local:
                key = LOCAL_KEY_PLACEHOLDER
            else:
                return {"ok": False, "error": "API key is empty — fill it in first."}
        if not model:
            return {"ok": False, "error": "Model name is empty — fill it in first."}
        try:
            from openai import OpenAI
            cli = OpenAI(api_key=key, base_url=base or None, timeout=30,
                         default_headers=_session_headers())
            t0 = _time.time()
            r = cli.chat.completions.create(
                model=model, max_tokens=8,
                messages=[{"role": "user", "content": "Reply with one word: ok"}])
            reply = ""
            if getattr(r, "choices", None):
                reply = getattr(r.choices[0].message, "content", "") or ""
            return {"ok": True,
                    "latency_seconds": round(_time.time() - t0, 1),
                    "reply": reply.strip()[:40]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300]}

    # ------------------------------------------------------ writing map ----

    def writing_map(self, tid: str) -> dict:
        draft = self.db.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
        if not draft:
            return {"beats": []}
        beats = self.engine.writing_map(plan=self._latest_plan(tid),
                                        content=draft["working_content"])
        return {"beats": beats}


def _session_headers() -> dict[str, str]:
    """Send a stable session id so OpenCode Go can optimize routing/caching."""
    import os as _os
    import uuid

    _os.environ.setdefault(
        "OPENCODE_SESSION_ID",
        f"{_now_like()}-{uuid.uuid4().hex}")
    return {"x-opencode-session": _os.environ["OPENCODE_SESSION_ID"]}


def _now_like() -> str:
    import time as _t
    return _t.strftime("%Y%m%d", _t.localtime())


_ORIGINS = {
    "generation": "Initial Generation",
    "patch": "AI Patch",
    "manual_checkpoint": "Manual Checkpoint",
    "restore": "Restore",
}
