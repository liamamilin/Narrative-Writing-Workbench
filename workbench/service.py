"""Workbench product services: CRUD + hard invariants (product/06).

Golden rules enforced here:
- AI proposes, user accepts: a ProposedPatch never mutates the Draft.
- Accept creates a Version; Reject creates nothing.
- Generation/patch failure leaves existing content untouched.
- Restore is itself a new version (reversible).
- Autosave writes working_content only; it never creates versions.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from . import meaning_schema
from .evidence_schema import validate_evidence
from .reader_path_schema import validate_reader_path
from . import settings as settings_mod
from .backup import (BackupError, create_backup as build_workspace_backup,
                     inspect_backup as inspect_workspace_backup,
                     restore_backup as restore_workspace_backup)
from .db import Database, new_id
from .engine import (EngineError, LockConflict,
                     get_engine)
from .exporting import build_export
from .operations import CURRENT, tracked, recover_interrupted

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
EVIDENCE_TASK_TYPES = {"narrative_analysis", "character_analysis", "essay"}
EVIDENCE_MAX_DRAFT_CHARS = 20_000
EVIDENCE_MAX_SOURCES = 20
EVIDENCE_MAX_SOURCE_CHARS = 60_000
READER_PATH_MAX_DRAFT_CHARS = 30_000
READER_PATH_MAX_PARAGRAPHS = 80
READER_PATH_MAX_PARAGRAPH_CHARS = 10_000
IDEA_STATUSES = {"to_write", "written", "archived"}
IDEA_ORIGINS = {"manual", "generated", "legacy"}
IDEA_MAX_TOPIC_CHARS = 500
IDEA_MAX_HOOK_CHARS = 500
IDEA_MAX_NOTE_CHARS = 2_000
IDEA_MAX_DOMAIN_CHARS = 120
IDEA_IMPORT_MAX = 200
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


def normalize_idea_topic(topic: str) -> str:
    """Narrow, explainable equality for Idea deduplication."""
    return " ".join(unicodedata.normalize("NFKC", topic).split()).casefold()


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
    s = payload.get("summary") or {}
    parts = [f"{_REVIEW_DIM_ZH[k]}:{_REVIEW_LABEL_ZH.get(s.get(k), s.get(k))}"
             for k in _REVIEW_DIM_ZH if s.get(k)]
    n = len(payload.get("issues") or [])
    base = ("检查:" + " · ".join(parts)
            + (f";{n} 个可改进点" if n else ";未发现明显问题"))
    if s.get("decision") == "PATCH_REQUIRED":
        base += "。⚠ 未通过检查——这篇还没有兑现命题,建议针对性修订或换角度重写"
    return base


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


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def unique_quote_span(content: str, quote: str, start: int = 0,
                      end: int | None = None) -> tuple[int, int] | None:
    """Locate one exact quote inside a bounded range; ambiguity is unsafe."""
    if not isinstance(quote, str) or not quote or not (0 <= start <= len(content)):
        return None
    end = len(content) if end is None else end
    if not (start <= end <= len(content)):
        return None
    first = content.find(quote, start, end)
    if first < 0 or content.find(quote, first + 1, end) >= 0:
        return None
    return first, first + len(quote)


def paragraph_range_for_span(content: str, char_start: int,
                             char_end: int) -> tuple[int, int]:
    """Return the 1-based paragraphs touched by an exact character span."""
    if not (0 <= char_start < char_end <= len(content)):
        raise ApiError("PRESERVED_TEXT_CONFLICT", "保留片段的位置已失效。", 409, True)
    start = content[:char_start].count("\n\n") + 1
    end = content[:max(char_start, char_end - 1)].count("\n\n") + 1
    return start, end


class Service:
    def __init__(self, db: Database | None = None, engine=None,
                 restore_root: str | Path | None = None):
        self.db = db or Database()
        self.engine = engine or get_engine()
        if restore_root is None:
            base = (Path(self.db.path).resolve().parent
                    if self.db.path != ":memory:"
                    else Path(__file__).resolve().parent)
            restore_root = base / "restored"
        self.restore_root = Path(restore_root)
        recover_interrupted(self.db)

    def _operation_view(self, tid):
        return self.db.q1("SELECT id,kind,status,stage,started_at,finished_at,elapsed_ms,error_code,retry_of FROM writing_operations WHERE task_id=? ORDER BY rowid DESC LIMIT 1", (tid,))

    def operation_detail(self, tid, oid):
        self.get_task(tid)
        row = self.db.q1("SELECT id,kind,status,stage,started_at,finished_at,elapsed_ms,error_code,retry_of,result_json,usage_json FROM writing_operations WHERE task_id=? AND id=?", (tid, oid))
        if not row:
            raise ApiError("NOT_FOUND", "Operation not found.", 404)
        row["result"] = json.loads(row.pop("result_json") or "{}")
        row["usage"] = json.loads(row.pop("usage_json") or "null")
        row["events"] = [dict(seq=e["seq"], kind=e["kind"], data=json.loads(e["data_json"]), elapsed_ms=e["elapsed_ms"])
                         for e in self.db.q("SELECT * FROM operation_events WHERE operation_id=? ORDER BY seq", (oid,))]
        row["unapplied_result"] = self.db.q1(
            "SELECT id,content FROM generation_results WHERE operation_id=? AND accepted_version_id IS NULL ORDER BY rowid DESC LIMIT 1", (oid,))
        row["records"] = [
            {"category": r["category"], "name": r["name"],
             "status": r["status"], "data": json.loads(r["data_json"]),
             "elapsed_ms": r["elapsed_ms"]}
            for r in self.db.q(
                "SELECT category,name,status,data_json,elapsed_ms FROM operation_records "
                "WHERE operation_id=? ORDER BY rowid", (oid,))]
        return row

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

    # --------------------------------------------------------------- ideas ----

    @staticmethod
    def _idea_text(value, field: str, maximum: int, *, required: bool = False) -> str:
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ApiError("VALIDATION", f"{field} must be text.")
        value = value.strip()
        if required and not value:
            raise ApiError("VALIDATION", "请先写下要收藏的话题。")
        if len(value) > maximum:
            raise ApiError("VALIDATION", f"{field} is too long.")
        return value

    @staticmethod
    def _idea_source_key(origin: str, normalized: str, domain: str,
                         hook: str) -> str:
        raw = json.dumps([origin, normalized, domain, hook], ensure_ascii=False,
                         separators=(",", ":"))
        return f"{origin}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"

    def _validated_idea(self, payload: dict, *, legacy: bool = False) -> dict:
        if not isinstance(payload, dict):
            raise ApiError("VALIDATION", "Idea must be an object.")
        topic = self._idea_text(payload.get("topic", payload.get("text")),
                                "topic", IDEA_MAX_TOPIC_CHARS, required=True)
        hook = self._idea_text(payload.get("hook"), "hook", IDEA_MAX_HOOK_CHARS)
        note = self._idea_text(payload.get("note"), "note", IDEA_MAX_NOTE_CHARS)
        domain = self._idea_text(payload.get("domain"), "domain", IDEA_MAX_DOMAIN_CHARS)
        domain_name = self._idea_text(payload.get("domain_name", payload.get("domainName")),
                                     "domain_name", IDEA_MAX_DOMAIN_CHARS)
        origin = "legacy" if legacy else str(payload.get("origin") or "manual")
        if origin not in IDEA_ORIGINS or (not legacy and origin == "legacy"):
            raise ApiError("VALIDATION", "origin must be manual or generated.")
        normalized = normalize_idea_topic(topic)
        if not normalized:
            raise ApiError("VALIDATION", "请先写下要收藏的话题。")
        return {"topic": topic, "normalized_topic": normalized, "hook": hook,
                "domain": domain, "domain_name": domain_name, "note": note,
                "origin": origin,
                "source_key": self._idea_source_key(origin, normalized, domain, hook)}

    def _idea_row(self, idea_id: str) -> dict:
        row = self.db.q1("SELECT * FROM ideas WHERE id=?", (idea_id,))
        if not row:
            raise ApiError("NOT_FOUND", "选题不存在。", 404)
        return row

    def create_idea(self, payload: dict) -> dict:
        data = self._validated_idea(payload)
        with self.db.transaction() as tx:
            existing = tx.q1("SELECT * FROM ideas WHERE normalized_topic=?",
                             (data["normalized_topic"],))
            if existing:
                return {"idea": existing, "created": False}
            idea_id, ts = new_id("idea"), now()
            tx.exec(
                "INSERT INTO ideas(id,topic,normalized_topic,hook,domain,domain_name,note,"
                "origin,source_key,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,'to_write',?,?)",
                (idea_id, data["topic"], data["normalized_topic"], data["hook"],
                 data["domain"], data["domain_name"], data["note"], data["origin"],
                 data["source_key"], ts, ts))
            row = tx.q1("SELECT * FROM ideas WHERE id=?", (idea_id,))
        return {"idea": row, "created": True}

    def list_ideas(self, query: str = "", status: str = "all",
                   limit: int = 100) -> dict:
        if status not in IDEA_STATUSES | {"all"}:
            raise ApiError("VALIDATION", "Unknown idea status.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ApiError("VALIDATION", "limit must be an integer in 1..200.")
        query = self._idea_text(query, "q", 100)
        where, args = [], []
        if status != "all":
            where.append("status=?"); args.append(status)
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where.append("(topic LIKE ? ESCAPE '\\' OR note LIKE ? ESCAPE '\\' "
                         "OR domain_name LIKE ? ESCAPE '\\')")
            args.extend([f"%{escaped}%"] * 3)
        sql = "SELECT * FROM ideas"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += (" ORDER BY CASE status WHEN 'to_write' THEN 0 WHEN 'written' THEN 1 ELSE 2 END,"
                " updated_at DESC,rowid DESC LIMIT ?")
        args.append(limit)
        rows = self.db.q(sql, tuple(args))
        counts = {row["status"]: row["count"] for row in self.db.q(
            "SELECT status,count(*) AS count FROM ideas GROUP BY status")}
        return {"ideas": rows, "counts": {key: counts.get(key, 0)
                                            for key in ("to_write", "written", "archived")}}

    def update_idea(self, idea_id: str, payload: dict) -> dict:
        if not isinstance(payload, dict) or not payload or not set(payload) <= {"note", "status"}:
            raise ApiError("VALIDATION", "Only note and status can be updated.")
        sets, args, requested_status = [], [], None
        if "note" in payload:
            sets.append("note=?")
            args.append(self._idea_text(payload["note"], "note", IDEA_MAX_NOTE_CHARS))
        if "status" in payload:
            status = payload["status"]
            if status not in IDEA_STATUSES:
                raise ApiError("VALIDATION", "Unknown idea status.")
            requested_status = status
            sets.append("status=?"); args.append(status)
        args.extend([now(), idea_id])
        with self.db.transaction() as tx:
            current = tx.q1("SELECT * FROM ideas WHERE id=?", (idea_id,))
            if not current:
                raise ApiError("NOT_FOUND", "选题不存在。", 404)
            if requested_status == "to_write" and current.get("task_id"):
                raise ApiError("IDEA_HAS_TASK", "已关联文章的选题不能改回待写。", 409)
            if requested_status == "written" and not current.get("task_id"):
                raise ApiError("IDEA_HAS_NO_TASK", "选题关联文章后才会变为已写。", 409)
            tx.exec(f"UPDATE ideas SET {','.join(sets)},updated_at=? WHERE id=?", tuple(args))
            row = tx.q1("SELECT * FROM ideas WHERE id=?", (idea_id,))
        return row

    def import_legacy_ideas(self, payload: dict) -> dict:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list) or len(items) > IDEA_IMPORT_MAX:
            raise ApiError("VALIDATION", "Legacy items must be an array of at most 200 entries.")
        validated = [self._validated_idea(item, legacy=True) for item in items]
        imported = existing_count = 0
        with self.db.transaction() as tx:
            for data in validated:
                if tx.q1("SELECT id FROM ideas WHERE normalized_topic=?",
                         (data["normalized_topic"],)):
                    existing_count += 1
                    continue
                idea_id, ts = new_id("idea"), now()
                tx.exec(
                    "INSERT INTO ideas(id,topic,normalized_topic,hook,domain,domain_name,note,"
                    "origin,source_key,status,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,'to_write',?,?)",
                    (idea_id, data["topic"], data["normalized_topic"], data["hook"],
                     data["domain"], data["domain_name"], data["note"], "legacy",
                     data["source_key"], ts, ts))
                imported += 1
        return {"received": len(validated), "imported": imported,
                "existing": existing_count}

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
        idea_id = payload.get("idea_id")

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
        if input_mode == "draft_revision" and not material:
            raise ApiError("VALIDATION", "请先粘贴要修改的旧稿。")
        for sid in payload.get("source_ids") or []:
            if not self.db.q1("SELECT id FROM sources WHERE id=?", (sid,)):
                raise ApiError("NOT_FOUND", f"Source {sid} not found.", 404)
        with self.db.transaction() as tx:
            idea = None
            if idea_id:
                idea = tx.q1("SELECT * FROM ideas WHERE id=?", (idea_id,))
                if not idea:
                    raise ApiError("NOT_FOUND", "选题不存在。", 404)
                if input_mode != "topic_only":
                    raise ApiError("VALIDATION", "选题只能关联快速写作任务。")
                if idea.get("task_id"):
                    raise ApiError("IDEA_ALREADY_LINKED", "这个选题已有文章，请直接打开。", 409)
                if idea["normalized_topic"] != normalize_idea_topic(topic):
                    raise ApiError("IDEA_TOPIC_MISMATCH", "当前话题与收藏的选题不一致。", 409)
            tid = new_id("task")
            ts = now()
            tx.exec(
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
            tx.exec("INSERT INTO writing_configs VALUES(?,?,?,?,?,?,?)",
                         (tid, cfg.get("immersion"), cfg.get("explicitness"),
                          cfg.get("intensity"), cfg.get("target_length"),
                          json.dumps(locks, ensure_ascii=False),
                          json.dumps(cfg.get("constraints") or {}, ensure_ascii=False)))
            if material:
                sid = new_id("src")
                tx.exec("INSERT INTO sources(id,project_id,title,type,content,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                        (sid, project_id, "Task material", "pasted_text", material, ts, ts))
                tx.exec("INSERT INTO task_sources VALUES(?,?,?)", (tid, sid, "primary"))
            for sid in payload.get("source_ids") or []:
                tx.exec("INSERT OR IGNORE INTO task_sources VALUES(?,?,?)",
                             (tid, sid, "context"))
            if input_mode == "draft_revision":
                did = new_id("draft")
                tx.exec("INSERT INTO drafts(id,task_id,working_content,updated_at) VALUES(?,?,?,?)", (did, tid, material, ts))
                draft = tx.q1("SELECT * FROM drafts WHERE id=?", (did,))
                self._version_write(tx, draft, material, "manual_checkpoint", instruction="导入原稿")
                tx.exec("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
            if idea:
                tx.exec("UPDATE ideas SET task_id=?,status='written',updated_at=? WHERE id=?",
                        (tid, ts, idea_id))
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
                 "selection": json.loads(p["selection_json"]),
                 "revision_item_id": p.get("revision_item_id"),
                 "claim_link_id": p.get("claim_link_id")}
                for p in self.db.q(
                    "SELECT * FROM proposed_patches WHERE draft_id=? AND status='proposed' "
                    "ORDER BY created_at,rowid",
                    (draft["id"],))]
        task["operation"] = self._operation_view(tid)
        task["review"] = None
        if draft:
            row = self.db.q1("SELECT * FROM reviews WHERE draft_id=? AND analysis_type='writing' ORDER BY created_at DESC,rowid DESC LIMIT 1",
                             (draft["id"],))
            if row:
                task["review"] = self._review_payload(row, task, draft)
        task["evidence_check"] = None
        if draft:
            check = self.db.q1(
                "SELECT * FROM claim_checks WHERE task_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
                (tid,))
            if check:
                task["evidence_check"] = self._evidence_payload(check, task, draft)
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
            if key in payload:
                value = payload[key]
                if value is None or value == "":
                    cfg[key] = None                 # explicit reset to auto
                elif value in EXPERIENCE_LEVELS:
                    cfg[key] = value
                else:
                    raise ApiError("VALIDATION", f"Invalid {key} value.")
        if "target_length" in payload:
            tl = payload["target_length"]
            if tl is None or tl == "":
                cfg["target_length"] = None     # explicit reset: no target
            else:
                try:
                    tl = int(tl)
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
        with self.db.transaction() as tx:
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
            tx.exec(f"UPDATE tasks SET {','.join(sets)} WHERE id=?",
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
                tx.exec(
                    "UPDATE writing_configs SET immersion=?,explicitness=?,intensity=?"
                    ",target_length=?,locks_json=?,constraints_json=? WHERE task_id=?",
                    (merged["immersion"], merged["explicitness"], merged["intensity"],
                     merged["target_length"],
                     json.dumps(merged["locks"] or {}, ensure_ascii=False),
                     json.dumps(merged["constraints"] or {}, ensure_ascii=False), tid))
            if any(key in payload for key in ("instruction", "expected_language", "config")):
                draft = tx.q1("SELECT id FROM drafts WHERE task_id=?", (tid,))
                if draft:
                    self._invalidate_revision_context(tx, draft["id"], preserve=False)
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
        draft = self.db.q1("SELECT id FROM drafts WHERE task_id=?", (tid,))
        if draft:
            with self.db.transaction() as tx:
                self._invalidate_revision_context(tx, draft["id"], preserve=False)
        return src

    def _record_mode_transition(self, tid, frm, to):
        cfg = self.db.q1("SELECT * FROM writing_configs WHERE task_id=?", (tid,))
        constraints = json.loads((cfg or {}).get("constraints_json") or "{}")
        history = constraints.setdefault("mode_transitions", [])
        history.append({"from": frm, "to": to, "at": now()})
        self.db.exec("UPDATE writing_configs SET constraints_json=? WHERE task_id=?",
                     (json.dumps(constraints, ensure_ascii=False), tid))

    # ---------------------------------------------------------- generate ----

    def _generation_task(self, tid, payload):
        task = self.get_task(tid)
        draft = self.db.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
        if draft:
            self._check_revision(draft, payload.get("expected_revision"))
        task = self._apply_param_overrides(task, payload)
        task["_base_draft"] = draft
        op = CURRENT.get()
        task["_engine_snapshot"] = op.snapshot
        op.bind_inputs(self._gen_inputs_fingerprint(task, None, self._material(task) or task["topic"]))
        return task

    @tracked("generate")
    def generate(self, tid: str, payload: dict | None = None) -> dict:
        payload = payload or {}
        task = self._generation_task(tid, payload)
        if task.get("input_mode") == "draft_revision":
            raise ApiError("DRAFT_REVISION", "旧稿已保留，请使用检查与局部修改。", 409)
        ch = CURRENT.get().channel
        ch.emit("stage", {"stage": "queued"})
        material = self._material(task)
        resume = bool(payload.get("resume"))
        confirmed_id = payload.get("confirmed_meaning_id")
        if task.get("input_mode") != "topic_only":
            if confirmed_id:
                raise ApiError("CONFIRMED_MEANING_REQUIRED",
                               "Confirmed angles only apply to Quick Write tasks.", 409)
            if not material and not task["instruction"]:
                ch.close()
                raise ApiError("VALIDATION", "Add material or an intent first.")
            try:
                plan = self._resumable_plan(task) if resume else None
                return self._generate_with(task, meaning=None, plan=plan)
            finally:
                ch.close()
        # Quick Write golden path: Meaning Discovery -> Angle -> WIR -> Writer
        try:
            if confirmed_id:
                discovery = self._confirmed_discovery(task, confirmed_id)
                CURRENT.get().bind_inputs(
                    self._gen_inputs_fingerprint(task, discovery,
                                                 material or task["topic"]))
                ch.emit("angle", meaning_schema.product_safe_summary(discovery["data"]))
                ch.emit("stage_summary", {
                    "stage": "discovery",
                    "text": "使用已确认角度 —— "
                            + meaning_schema.selected_angle(discovery["data"])
                                            .get("label", "已确定")})
                plan = self._resumable_plan(task, discovery) if resume else None
                return self._generate_with(task, meaning=discovery,
                                           material=material or task["topic"],
                                           plan=plan)
            if resume:
                discovery = self._resumable_discovery(task)
                if discovery:
                    ch.emit("stage_summary", {
                        "stage": "discovery",
                        "text": "复用上次发现的角度 —— "
                        + (meaning_schema.selected_angle(discovery["data"])
                           .get("label", "") or "已确定")})
                    ch.emit("angle",
                            meaning_schema.product_safe_summary(discovery["data"]))
            if not resume or not discovery:
                discovery = self.discover(task, emit=ch.emit,
                                          purpose="automatic")
            plan = self._resumable_plan(task, discovery) if resume else None
            if not material:
                material = task["topic"]
            return self._generate_with(task, meaning=discovery,
                                       material=material, plan=plan)
        finally:
            ch.close()

    def discover(self, task: dict, avoid: list[str] | None = None,
                 emit=None, purpose: str = "automatic") -> dict:
        """Run Meaning Discovery, validate, persist (append-only lineage)."""
        tid = task["id"]
        avoid = avoid if avoid is not None else self._past_angle_labels(
            tid, include_options=purpose == "angle_options")
        discovery_inputs = self._discovery_inputs(task, CURRENT.get().snapshot)
        CURRENT.get().discovery_inputs = self._discovery_metadata(
            task, purpose, discovery_inputs)
        self.db.exec("UPDATE tasks SET status='generating',updated_at=? WHERE id=?",
                     (now(), tid))
        stage_cb = _stage_stream(emit, "discovery") if (emit and _debug_stream()) else None
        try:
            data = CURRENT.get().engine.discover_meaning(
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
        op = CURRENT.get()
        if op:
            self.db.exec("UPDATE meaning_discoveries SET operation_id=?,inputs_json=? WHERE id=?",
                         (op.id, json.dumps(op.discovery_inputs, ensure_ascii=False), mid))
        row = self.db.q1("SELECT * FROM meaning_discoveries WHERE id=?", (mid,))
        row["data"] = data if status == "ready" else None
        return row

    def _discovery_inputs(self, task, snapshot):
        return {"topic": task["topic"], "writing_mode": task.get("writing_mode"),
                "angle_mode": task.get("angle_mode"), "custom_angle": task.get("custom_angle"),
                "config": self._config_dict(task), "engine": snapshot}

    def _angle_task_inputs(self, task: dict) -> dict:
        return {
            "input_mode": task.get("input_mode"),
            "topic": task.get("topic"),
            "instruction": task.get("instruction"),
            "writing_mode": task.get("writing_mode"),
            "angle_mode": task.get("angle_mode"),
            "custom_angle": task.get("custom_angle"),
            "expected_language": task.get("expected_language"),
            "config": self._config_dict(task),
        }

    def _angle_task_fingerprint(self, task: dict) -> str:
        payload = json.dumps(self._angle_task_inputs(task), sort_keys=True,
                             ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _discovery_metadata(self, task: dict, purpose: str,
                            discovery_inputs: dict, **extra) -> dict:
        return {
            "purpose": purpose,
            "task_inputs": self._angle_task_inputs(task),
            "task_fingerprint": self._angle_task_fingerprint(task),
            "discovery_inputs": discovery_inputs,
            **extra,
        }

    @staticmethod
    def _discovery_meta(row: dict) -> dict:
        try:
            value = json.loads(row.get("inputs_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}
        return value if isinstance(value, dict) else {}

    @classmethod
    def _discovery_purpose(cls, row: dict) -> str:
        return cls._discovery_meta(row).get("purpose") or "automatic"

    @classmethod
    def _stored_discovery_inputs(cls, row: dict) -> dict:
        meta = cls._discovery_meta(row)
        return meta.get("discovery_inputs", meta)

    def _resumable_discovery(self, task):
        row = self._latest_discovery(task["id"])
        if row and self._stored_discovery_inputs(row) == self._discovery_inputs(task, CURRENT.get().snapshot):
            return row
        return None

    def _past_angle_labels(self, tid: str,
                           include_options: bool = False) -> list[str]:
        labels = []
        for r in self.db.q("SELECT data_json,inputs_json FROM meaning_discoveries "
                           "WHERE task_id=? AND status='ready'", (tid,)):
            try:
                d = json.loads(r["data_json"])
            except json.JSONDecodeError:
                continue
            for c in d.get("candidate_angles", []):
                is_options = self._discovery_purpose(r) == "angle_options"
                include_all = include_options and is_options
                if c.get("label") and (include_all or
                                       (not is_options and
                                        c.get("id") == d.get("selected_angle_id"))):
                    labels.append(c["label"])
        return labels

    def _latest_discovery(self, tid: str) -> dict | None:
        rows = self.db.q("SELECT * FROM meaning_discoveries WHERE task_id=?"
                         " AND status='ready'"
                         " ORDER BY created_at DESC, rowid DESC", (tid,))
        for row in rows:
            if self._discovery_purpose(row) == "angle_options":
                continue
            row["data"] = json.loads(row["data_json"])
            return row
        return None

    def _angle_options_payload(self, task: dict, row: dict) -> dict:
        meta = self._discovery_meta(row)
        return {
            "task_id": task["id"],
            "discovery_id": row["id"],
            "stale": meta.get("task_fingerprint") !=
                     self._angle_task_fingerprint(task),
            "candidates": meaning_schema.product_safe_candidates(row["data"]),
        }

    def _angle_options_row(self, tid: str, discovery_id: str) -> dict:
        row = self.db.q1("SELECT * FROM meaning_discoveries WHERE id=?",
                         (discovery_id,))
        if not row:
            raise ApiError("NOT_FOUND", "Angle options not found.", 404)
        if row["task_id"] != tid:
            raise ApiError("WRONG_TASK", "Angle options belong to another task.", 409)
        if row["status"] != "ready" or self._discovery_purpose(row) != "angle_options":
            raise ApiError("ANGLE_OPTIONS_REQUIRED",
                           "Select from an angle-options discovery.", 409)
        row["data"] = json.loads(row["data_json"])
        return row

    @tracked("angle_options")
    def angle_options(self, tid: str, payload: dict | None = None) -> dict:
        payload = payload or {}
        task = self.get_task(tid)
        if task.get("input_mode") != "topic_only":
            raise ApiError("ANGLE_OPTIONS_REQUIRED",
                           "Angle options are available for Quick Write tasks.", 409)
        if self.db.q1("SELECT id FROM drafts WHERE task_id=?", (tid,)):
            raise ApiError("ANGLE_OPTIONS_REQUIRED",
                           "This task already has a draft.", 409)
        task = self._apply_param_overrides(task, payload)
        task["_engine_snapshot"] = CURRENT.get().snapshot
        CURRENT.get().bind_inputs({"angle_options": self._angle_task_inputs(task)})
        ch = CURRENT.get().channel
        ch.emit("stage", {"stage": "queued"})
        try:
            row = self.discover(task, emit=ch.emit, purpose="angle_options")
            self.db.exec("UPDATE tasks SET status='draft',updated_at=? WHERE id=?",
                         (now(), tid))
            return self._angle_options_payload(task, row)
        finally:
            ch.close()

    def get_angle_options(self, tid: str, discovery_id: str) -> dict:
        task = self.get_task(tid)
        return self._angle_options_payload(
            task, self._angle_options_row(tid, discovery_id))

    @tracked("confirm_angle")
    def confirm_angle(self, tid: str, payload: dict) -> dict:
        task = self.get_task(tid)
        if task.get("input_mode") != "topic_only":
            raise ApiError("ANGLE_OPTIONS_REQUIRED",
                           "Angle confirmation is available for Quick Write tasks.", 409)
        discovery_id = payload.get("discovery_id")
        candidate_id = payload.get("candidate_id")
        if not isinstance(discovery_id, str) or not isinstance(candidate_id, str):
            raise ApiError("VALIDATION", "discovery_id and candidate_id are required.")
        source = self._angle_options_row(tid, discovery_id)
        meta = self._discovery_meta(source)
        if meta.get("task_fingerprint") != self._angle_task_fingerprint(task):
            raise ApiError("STALE_ANGLE_OPTIONS",
                           "Writing inputs changed. Find a new set of angles.", 409)
        data = json.loads(json.dumps(source["data"], ensure_ascii=False))
        selected = next((c for c in data.get("candidate_angles", [])
                         if c.get("id") == candidate_id), None)
        if not selected:
            raise ApiError("VALIDATION", "candidate_id is not in this discovery.")
        fields = {"label", "core_question", "deep_meaning", "boundary",
                  "reader_end_state"}
        edits = payload.get("edits")
        if edits is not None:
            if not isinstance(edits, dict) or set(edits) != fields:
                raise ApiError("VALIDATION",
                               "edits must contain the complete editable angle card.")
            for key, value in edits.items():
                if not isinstance(value, str) or not value.strip() or len(value.strip()) > 2000:
                    raise ApiError("VALIDATION", f"Invalid angle field: {key}.")
            changed = any(edits[k].strip() !=
                          str(selected.get(k) or data.get(k) or "").strip()
                          for k in fields)
            selected.update({k: edits[k].strip() for k in fields})
        else:
            changed = False
            selected["boundary"] = selected.get("boundary") or data.get("boundary", "")
        data["selected_angle_id"] = candidate_id
        for key in ("core_question", "deep_meaning", "boundary", "reader_end_state"):
            data[key] = selected[key]
        data["new_reading"] = selected["deep_meaning"]
        data["refined_thesis"] = selected["label"]
        data["crack"] = selected.get("crack") or data["crack"]
        data["strongest_counterexample"] = (
            selected.get("strongest_counterexample") or data["strongest_counterexample"])
        errors = meaning_schema.validate_meaning(data)
        if errors:
            raise ApiError("VALIDATION", "The confirmed angle is incomplete or inconsistent.")
        CURRENT.get().bind_inputs({"confirm_angle": self._angle_task_inputs(task),
                                   "discovery_id": discovery_id,
                                   "candidate_id": candidate_id})
        CURRENT.get().discovery_inputs = self._discovery_metadata(
            task, "confirmed", self._stored_discovery_inputs(source),
            parent_discovery_id=discovery_id,
            selected_candidate_id=candidate_id,
            selection_source="edited" if changed else "candidate")
        row = self._persist_discovery(tid, task["topic"], candidate_id,
                                      "ready", data)
        return {"task_id": tid, "confirmed_meaning_id": row["id"],
                "meaning": meaning_schema.product_safe_summary(data)}

    def _confirmed_discovery(self, task: dict, meaning_id: str) -> dict:
        row = self.db.q1("SELECT * FROM meaning_discoveries WHERE id=?", (meaning_id,))
        if not row:
            raise ApiError("NOT_FOUND", "Confirmed angle not found.", 404)
        if row["task_id"] != task["id"]:
            raise ApiError("WRONG_TASK", "Confirmed angle belongs to another task.", 409)
        meta = self._discovery_meta(row)
        if row["status"] != "ready" or meta.get("purpose") != "confirmed":
            raise ApiError("CONFIRMED_MEANING_REQUIRED",
                           "Confirm an angle before using it to write.", 409)
        if meta.get("task_fingerprint") != self._angle_task_fingerprint(task):
            raise ApiError("STALE_ANGLE_OPTIONS",
                           "Writing inputs changed. Confirm a new angle.", 409)
        row["data"] = json.loads(row["data_json"])
        return row

    def _gen_inputs_fingerprint(self, task: dict, meaning: dict | None,
                                material: str) -> dict:
        """Snapshot of every input the WIR stage consumes. A plan is only
        reusable when this matches the snapshot stored with it."""
        cfg = task["config"]
        return {
            "engine": task.get("_engine_snapshot"),
            "instruction": task["instruction"],
            "dials": {k: cfg.get(k) for k in
                      ("immersion", "explicitness", "intensity")},
            "target_length": cfg.get("target_length"),
            "expected_language": task.get("expected_language"),
            "locks": cfg.get("locks"),
            "constraints": cfg.get("constraints"),
            "meaning_id": (meaning or {}).get("id"),
            "material_sha": hashlib.sha256(
                (material or "").encode("utf-8")).hexdigest(),
        }

    def _resumable_plan(self, task: dict,
                        meaning: dict | None = None) -> dict | None:
        """Latest plan for this task, valid only if inputs still match."""
        row = self.db.q1(
            "SELECT id, data_json, inputs_json FROM engine_plans WHERE task_id=?"
            " ORDER BY created_at DESC, rowid DESC LIMIT 1", (task["id"],))
        if not row:
            return None
        try:
            saved = json.loads(row["inputs_json"] or "{}")
        except json.JSONDecodeError:
            return None
        material = self._material(task) or task["topic"]
        if saved != self._gen_inputs_fingerprint(task, meaning, material):
            return None
        try:
            return {**json.loads(row["data_json"]), "_plan_id": row["id"]}
        except json.JSONDecodeError:
            return None

    def _generate_with(self, task: dict, meaning: dict | None,
                       material: str | None = None,
                       plan: dict | None = None) -> dict:
        tid = task["id"]
        ch = CURRENT.get().channel
        emit = ch.emit
        stream = _delta_stream(ch)
        struct_cb = (_stage_stream(emit, "structure")
                     if _debug_stream() else None)
        if material is None:
            material = self._material(task)
        self.db.exec("UPDATE tasks SET status='generating',updated_at=? WHERE id=?",
                     (now(), tid))
        plan_id = (plan or {}).get("_plan_id")
        if plan:
            on_plan = None      # resume: architect skipped, plan row exists
        else:
            def on_plan(new_plan: dict) -> None:
                nonlocal plan_id
                plan_id = new_id("plan")
                # Persist the WIR the moment the Architect finishes: if the
                # Writer or gates fail, this node is already saved and a
                # resume can skip straight to writing.
                self.db.exec(
                    "INSERT INTO engine_plans(id,task_id,schema_version,"
                    "data_json,created_at,meaning_id,inputs_json)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (plan_id, tid, "1",
                     json.dumps(new_plan, ensure_ascii=False), now(),
                     (meaning or {}).get("id"),
                     json.dumps(self._gen_inputs_fingerprint(
                         task, meaning, material), ensure_ascii=False)))
                self.db.exec("UPDATE engine_plans SET operation_id=? WHERE id=?", (CURRENT.get().id, plan_id))
        try:
            result = CURRENT.get().engine.generate(
                material=material, instruction=task["instruction"],
                task_type=task["type"], config=self._config_dict(task),
                meaning=(meaning or {}).get("data") if meaning else None,
                emit=emit, on_delta=stream, on_struct_delta=struct_cb,
                plan=plan, on_plan=on_plan)
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
        if not plan_id:
            # Adapters may return a plan without supporting the early callback.
            plan_id = new_id("plan")
            self.db.exec("INSERT INTO engine_plans(id,task_id,data_json,created_at,meaning_id)"
                         " VALUES(?,?,?,?,?)", (plan_id, tid, json.dumps(result.plan), now(),
                                                (meaning or {}).get("id")))
        result_id = new_id("result")
        self.db.exec("UPDATE engine_plans SET operation_id=COALESCE(operation_id,?) WHERE id=?", (CURRENT.get().id, plan_id))
        self.db.exec("INSERT INTO generation_results(id,task_id,engine_plan_id,content,accepted_version_id,created_at) VALUES(?,?,?,?,?,?)",
                     (result_id, tid, plan_id, result.text, None, now()))
        self.db.exec("UPDATE generation_results SET operation_id=? WHERE id=?", (CURRENT.get().id, result_id))
        try:
            with self.db.transaction() as tx:
                draft = tx.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
                base = task.get("_base_draft")
                if base:
                    if not draft or draft["id"] != base["id"]:
                        raise ApiError("STALE_BASE", "正文已改变，请重新载入。", 409, True)
                    self._check_revision(draft, base["revision"])
                elif draft:
                    raise ApiError("STALE_BASE", "已有另一份初稿，请重新载入。", 409, True)
                else:
                    did = new_id("draft")
                    tx.exec("INSERT INTO drafts(id,task_id,current_version_id,working_content,updated_at)"
                            " VALUES(?,?,?,?,?)", (did, tid, None, "", now()))
                    draft = tx.q1("SELECT * FROM drafts WHERE id=?", (did,))
                draft = self._preserve_working_copy(tx, draft)
                vid, revision = self._version_write(
                    tx, draft, result.text, "generation", plan_id=plan_id)
                self._invalidate_revision_context(tx, draft["id"], preserve=True)
                tx.exec("UPDATE generation_results SET accepted_version_id=? WHERE id=?", (vid, result_id))
                tx.exec("UPDATE tasks SET status='ready',updated_at=? WHERE id=?", (now(), tid))
        except Exception:
            self.db.exec("UPDATE tasks SET status='failed',updated_at=? WHERE id=?", (now(), tid))
            emit("error", {"message": "生成结果已保留，但未替换当前正文；请重新载入后重试。"})
            raise
        stream.flush()
        emit("done", {"version_id": vid})
        return {"task_id": tid, "draft_id": draft["id"], "version_id": vid,
                "content": result.text, "status": "completed", "revision": revision}

    # ------------------------------------------------------------ review ----

    @tracked("review")
    def review(self, tid: str) -> dict:
        task = self.get_task(tid)
        draft = self.db.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
        if not draft or not draft["working_content"].strip():
            raise ApiError("NO_DRAFT", "Generate a draft before review.", 409)
        CURRENT.get().bind_inputs({**self._review_config(task), "revision": draft["revision"],
                                   "content_hash": hashlib.sha256(draft["working_content"].encode()).hexdigest()})
        return self._review_inner(tid, task, draft)

    def _review_inner(self, tid: str, task: dict, draft: dict) -> dict:
        plan = self._plan_for_draft(draft)
        ch = CURRENT.get().channel
        rev_cb = _stage_stream(ch.emit, "review") if _debug_stream() else None
        ch.emit("stage", {"stage": "review"})
        try:
            try:
                payload = CURRENT.get().engine.review(
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
            rid, ts = new_id("rev"), now()
            digest = content_hash(draft["working_content"])
            normalized = []
            with self.db.transaction() as tx:
                current = tx.q1("SELECT * FROM drafts WHERE id=?", (draft["id"],))
                if (not current or current["revision"] != draft["revision"]
                        or content_hash(current["working_content"]) != digest):
                    raise ApiError("STALE_BASE", "正文在检查期间发生了变化，请重新检查。",
                                   409, True)
                self._invalidate_revision_context(tx, draft["id"], preserve=False)
                for index, raw in enumerate(payload.get("issues") or [], 1):
                    issue = dict(raw)
                    issue_id = str(issue.get("id") or f"issue_{index}")
                    loc = issue.get("location") or {}
                    ps, pe = loc.get("paragraph_start"), loc.get("paragraph_end")
                    try:
                        if type(ps) is not int or type(pe) is not int:
                            raise ApiError("INVALID_SELECTION", "Invalid review location.")
                        char_start, char_end = paragraph_span(
                            draft["working_content"], ps, pe)
                    except ApiError:
                        issue["fixable"] = False
                        normalized.append(issue)
                        continue
                    item_id = new_id("item")
                    quote = draft["working_content"][char_start:char_end]
                    severity = issue.get("severity")
                    if severity not in {"fatal", "major", "moderate", "minor"}:
                        severity = "moderate"
                    goal = str(issue.get("goal") or issue.get("action")
                               or issue.get("message") or "Revise this passage.")
                    effect = str(issue.get("effect") or "")
                    message = str(issue.get("message") or goal)
                    tx.exec(
                        "INSERT INTO revision_items(id,review_id,draft_id,issue_id,base_revision,"
                        "content_hash,paragraph_start,paragraph_end,char_start,char_end,quote,type,"
                        "severity,message,effect,goal,status,created_at,updated_at)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?,?)",
                        (item_id, rid, draft["id"], issue_id, draft["revision"], digest,
                         ps, pe, char_start, char_end, quote,
                         str(issue.get("type") or "issue"), severity, message, effect,
                         goal, ts, ts))
                    issue.update({"id": issue_id, "revision_item_id": item_id,
                                  "severity": severity, "effect": effect, "goal": goal,
                                  "quote": quote, "status": "open", "fixable": True})
                    normalized.append(issue)
                tx.exec(
                    "INSERT INTO reviews(id,draft_id,version_id,summary_json,issues_json,"
                    "created_at,content_hash,draft_revision,config_json,operation_id)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (rid, draft["id"], draft["current_version_id"],
                     json.dumps(payload["summary"], ensure_ascii=False),
                     json.dumps(normalized, ensure_ascii=False), ts, digest,
                     draft["revision"], json.dumps(self._review_config(task), ensure_ascii=False),
                     CURRENT.get().id))
            payload = {**payload, "issues": normalized}
            ch.emit("stage_summary", {"stage": "review",
                                      "text": _review_summary_text(payload)})
            ch.emit("done", {"review_id": rid})
            row = self.db.q1("SELECT * FROM reviews WHERE id=?", (rid,))
            current = self.db.q1("SELECT * FROM drafts WHERE id=?", (draft["id"],))
            return self._review_payload(row, self.get_task(tid), current)
        finally:
            if rev_cb:
                rev_cb.flush()
            ch.close()

    def _plan_for_draft(self, draft: dict) -> dict | None:
        row = self.db.q1("SELECT p.data_json FROM versions v JOIN engine_plans p"
                         " ON p.id=v.engine_plan_id WHERE v.id=? AND v.draft_id=?",
                         (draft["current_version_id"], draft["id"]))
        return json.loads(row["data_json"]) if row else None

    def _current_discovery(self, tid: str) -> dict | None:
        draft = self.db.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
        if not draft:
            return self._latest_discovery(tid)
        row = self.db.q1("SELECT m.* FROM versions v JOIN engine_plans p ON p.id=v.engine_plan_id"
                         " JOIN meaning_discoveries m ON m.id=p.meaning_id"
                         " WHERE v.id=? AND v.draft_id=? AND m.task_id=?",
                         (draft["current_version_id"], draft["id"], tid))
        if row:
            row["data"] = json.loads(row["data_json"])
        return row

    def _review_config(self, task):
        return {"config": self._config_dict(task), "instruction": task["instruction"],
                "material_hash": hashlib.sha256(self._material(task).encode()).hexdigest()}

    def _review_payload(self, row, task, draft):
        digest = content_hash(draft["working_content"])
        stale = (row["draft_revision"] != draft["revision"] or row["content_hash"] != digest
                 or json.loads(row["config_json"] or "null") != self._review_config(task))
        items = {item["issue_id"]: item for item in self.db.q(
            "SELECT * FROM revision_items WHERE review_id=? ORDER BY rowid", (row["id"],))}
        issues = []
        for raw in json.loads(row["issues_json"]):
            issue = dict(raw)
            item = items.get(issue.get("id"))
            if item:
                status = "stale" if stale and item["status"] in ("open", "proposed") else item["status"]
                issue.update({
                    "revision_item_id": item["id"], "status": status,
                    "severity": item["severity"], "message": item["message"],
                    "effect": item["effect"], "goal": item["goal"],
                    "quote": item["quote"],
                    "location": {"paragraph_start": item["paragraph_start"],
                                 "paragraph_end": item["paragraph_end"]},
                    "fixable": status == "open",
                })
            issues.append(issue)
        priority = {"fatal": 0, "major": 1, "moderate": 2, "minor": 3}
        issues.sort(key=lambda issue: (
            0 if issue.get("status") in ("open", "proposed") else 1,
            priority.get(issue.get("severity"), 9),
            (issue.get("location") or {}).get("paragraph_start", 10**9)))
        total = len(issues)
        return {"id": row["id"], "revision": row["draft_revision"], "stale": stale,
                "summary": json.loads(row["summary_json"]),
                "issues": issues[:3], "total_issue_count": total,
                "remaining_issue_count": sum(
                    issue.get("status") in ("open", "proposed") for issue in issues)}

    def revision_worklist(self, tid: str) -> dict:
        task = self.get_task(tid)
        draft = self.db.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
        if not draft:
            raise ApiError("NO_DRAFT", "Generate a draft before review.", 409)
        row = self.db.q1(
            "SELECT * FROM reviews WHERE draft_id=? AND analysis_type='writing' ORDER BY created_at DESC,rowid DESC LIMIT 1",
            (draft["id"],))
        if not row:
            return {"review_id": None, "revision": draft["revision"], "stale": False,
                    "items": []}
        review = self._review_payload(row, task, draft)
        return {"review_id": row["id"], "revision": row["draft_revision"],
                "stale": review["stale"], "items": review["issues"],
                "total_issue_count": review["total_issue_count"],
                "remaining_issue_count": review["remaining_issue_count"]}

    # ---------------------------------------------------------- evidence ----

    @staticmethod
    def _source_snapshot(task: dict) -> list[dict]:
        return sorted(({
            "id": source["id"], "role": source.get("role", "primary"),
            "content_hash": content_hash(source.get("content", "")),
        } for source in task.get("sources") or []), key=lambda item: item["id"])

    @staticmethod
    def _assert_evidence_available(task: dict, draft: dict | None) -> list[dict]:
        if (task.get("input_mode") != "source_grounded"
                or task.get("type") not in EVIDENCE_TASK_TYPES):
            raise ApiError("EVIDENCE_NOT_APPLICABLE",
                           "材料依据检查仅适用于有素材的分析与观点写作。", 409)
        if not draft or not draft.get("working_content", "").strip():
            raise ApiError("NO_DRAFT", "请先生成或导入正文。", 409)
        sources = [source for source in task.get("sources") or []
                   if source.get("content", "").strip()]
        if not sources:
            raise ApiError("NO_SOURCES", "请先添加用于核查的素材。", 409)
        if len(draft["working_content"]) > EVIDENCE_MAX_DRAFT_CHARS:
            raise ApiError("EVIDENCE_INPUT_TOO_LARGE",
                           "正文超过 20,000 字符，请缩小检查范围。", 413)
        if len(sources) > EVIDENCE_MAX_SOURCES:
            raise ApiError("EVIDENCE_INPUT_TOO_LARGE",
                           "关联素材超过 20 份，请缩小材料范围。", 413)
        if sum(len(source["content"]) for source in sources) > EVIDENCE_MAX_SOURCE_CHARS:
            raise ApiError("EVIDENCE_INPUT_TOO_LARGE",
                           "关联素材超过 60,000 字符，请缩小材料范围。", 413)
        return sources

    def _evidence_is_stale(self, check: dict, task: dict, draft: dict) -> bool:
        try:
            snapshot = json.loads(check["sources_json"])
        except (TypeError, json.JSONDecodeError):
            return True
        return (check["draft_id"] != draft["id"]
                or check["draft_revision"] != draft["revision"]
                or check["content_hash"] != content_hash(draft["working_content"])
                or snapshot != self._source_snapshot(task))

    def _evidence_payload(self, check: dict, task: dict, draft: dict) -> dict:
        stale = self._evidence_is_stale(check, task, draft)
        sources = {source["id"]: source for source in task.get("sources") or []}
        cards = []
        for link in self.db.q(
                "SELECT * FROM claim_links WHERE check_id=? ORDER BY paragraph_start,rowid",
                (check["id"],)):
            source = sources.get(link.get("source_id"))
            cards.append({
                "id": link["id"], "claim_id": link["claim_id"],
                "claim_type": link["claim_type"], "relation": link["relation"],
                "explanation": link["explanation"],
                "revision_goal": link["revision_goal"],
                "draft_quote": link["draft_quote"],
                "location": {"paragraph_start": link["paragraph_start"],
                             "paragraph_end": link["paragraph_end"]},
                "source_id": link.get("source_id"),
                "source_title": source.get("title") if source else None,
                "source_quote": link.get("source_quote"),
                "source_location": ({"char_start": link["source_char_start"],
                                     "char_end": link["source_char_end"]}
                                    if link.get("source_char_start") is not None else None),
                "user_status": link["user_status"],
                "patch_id": link.get("patch_id"),
                "actionable": not stale and link["user_status"] != "dismissed",
            })
        return {"id": check["id"], "revision": check["draft_revision"],
                "stale": stale, "created_at": check["created_at"], "cards": cards}

    @tracked("evidence_check")
    def check_evidence(self, tid: str) -> dict:
        task = self.get_task(tid)
        draft = self.db.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
        sources = self._assert_evidence_available(task, draft)
        snapshot = self._source_snapshot(task)
        digest = content_hash(draft["working_content"])
        CURRENT.get().bind_inputs({
            "revision": draft["revision"], "content_hash": digest,
            "sources": snapshot,
        })
        ch = CURRENT.get().channel
        callback = _stage_stream(ch.emit, "evidence_check") if _debug_stream() else None
        ch.emit("stage", {"stage": "evidence_check"})
        try:
            payload = CURRENT.get().engine.check_evidence(
                content=draft["working_content"], sources=sources,
                on_delta=callback)
        except EngineError as exc:
            raise ApiError("EVIDENCE_CHECK_FAILED", str(exc), 500, True) from exc
        except Exception as exc:
            log.exception("ungrouped evidence check error for %s", tid)
            raise ApiError("EVIDENCE_CHECK_FAILED",
                           f"材料依据检查失败:{type(exc).__name__} — 请重试。",
                           500, True) from exc
        finally:
            if callback:
                callback.flush()
        errors = validate_evidence(payload)
        if errors:
            raise ApiError("EVIDENCE_CHECK_FAILED",
                           "材料依据检查返回了无法验证的结构，请重试。", 500, True)

        check_id, ts = new_id("echeck"), now()
        source_by_id = {source["id"]: source for source in sources}
        normalized = []
        seen = set()
        for raw in payload.get("claims") or []:
            claim_id = raw["id"]
            if claim_id in seen:
                continue
            seen.add(claim_id)
            ps, pe = raw["paragraph_start"], raw["paragraph_end"]
            try:
                region_start, region_end = paragraph_span(
                    draft["working_content"], ps, pe)
            except ApiError:
                continue
            draft_anchor = unique_quote_span(
                draft["working_content"], raw["draft_quote"],
                region_start, region_end)
            if not draft_anchor:
                continue
            relation = raw["relation"]
            source = source_by_id.get(raw.get("source_id"))
            source_anchor = None
            if source and raw.get("source_quote"):
                source_anchor = unique_quote_span(source["content"], raw["source_quote"])
            explanation = raw["explanation"].strip()
            if not source_anchor:
                source = None
                if relation in ("supported", "conflict"):
                    relation = "insufficient"
                    explanation += "（材料引文无法逐字定位，已按证据不足处理。）"
            normalized.append({
                "id": new_id("claim"), "claim_id": claim_id,
                "claim_type": raw["claim_type"], "relation": relation,
                "explanation": explanation,
                "revision_goal": raw["revision_goal"].strip(),
                "paragraph_start": ps, "paragraph_end": pe,
                "draft_char_start": draft_anchor[0], "draft_char_end": draft_anchor[1],
                "draft_quote": raw["draft_quote"], "source": source,
                "source_anchor": source_anchor,
                "source_quote": raw.get("source_quote") if source_anchor else None,
            })

        with self.db.transaction() as tx:
            current = tx.q1("SELECT * FROM drafts WHERE id=?", (draft["id"],))
            live_task = self.get_task(tid)
            if (not current or current["revision"] != draft["revision"]
                    or content_hash(current["working_content"]) != digest
                    or self._source_snapshot(live_task) != snapshot):
                raise ApiError("STALE_BASE",
                               "正文或素材在检查期间发生了变化，请重新检查。", 409, True)
            tx.exec("INSERT INTO claim_checks(id,task_id,draft_id,operation_id,draft_revision,"
                    "content_hash,sources_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (check_id, tid, draft["id"], CURRENT.get().id, draft["revision"],
                     digest, json.dumps(snapshot, ensure_ascii=False), ts))
            for card in normalized:
                source = card["source"]
                anchor = card["source_anchor"]
                tx.exec(
                    "INSERT INTO claim_links(id,check_id,draft_id,claim_id,claim_type,relation,"
                    "explanation,revision_goal,paragraph_start,paragraph_end,draft_char_start,"
                    "draft_char_end,draft_quote,source_id,source_content_hash,source_char_start,"
                    "source_char_end,source_quote,user_status,created_at,updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'unreviewed',?,?)",
                    (card["id"], check_id, draft["id"], card["claim_id"],
                     card["claim_type"], card["relation"], card["explanation"],
                     card["revision_goal"], card["paragraph_start"], card["paragraph_end"],
                     card["draft_char_start"], card["draft_char_end"], card["draft_quote"],
                     source["id"] if source else None,
                     content_hash(source["content"]) if source else None,
                     anchor[0] if anchor else None, anchor[1] if anchor else None,
                     card["source_quote"], ts, ts))
        ch.emit("stage_summary", {"stage": "evidence_check",
                                  "text": f"材料依据：{len(normalized)} 项关键陈述"})
        ch.emit("done", {"evidence_check_id": check_id})
        check = self.db.q1("SELECT * FROM claim_checks WHERE id=?", (check_id,))
        return self._evidence_payload(check, self.get_task(tid), draft)

    def evidence_check(self, tid: str) -> dict:
        task = self.get_task(tid)
        draft = self.db.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
        if not draft:
            raise ApiError("NO_DRAFT", "请先生成或导入正文。", 409)
        check = self.db.q1(
            "SELECT * FROM claim_checks WHERE task_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
            (tid,))
        if not check:
            return {"id": None, "revision": draft["revision"],
                    "stale": False, "cards": []}
        return self._evidence_payload(check, task, draft)

    def _update_claim_status(self, link_id: str, status: str) -> dict:
        with self.db.transaction() as tx:
            link = tx.q1("SELECT * FROM claim_links WHERE id=?", (link_id,))
            if not link:
                raise ApiError("NOT_FOUND", "依据卡不存在。", 404)
            check = tx.q1("SELECT * FROM claim_checks WHERE id=?", (link["check_id"],))
            draft = tx.q1("SELECT * FROM drafts WHERE id=?", (link["draft_id"],))
            task = self.get_task(check["task_id"])
            if self._evidence_is_stale(check, task, draft):
                raise ApiError("STALE_EVIDENCE_CHECK",
                               "正文或素材已改变，请重新检查。", 409, True)
            tx.exec("UPDATE claim_links SET user_status=?,updated_at=? WHERE id=?",
                    (status, now(), link_id))
        return {"claim_link_id": link_id, "user_status": status,
                "relation": link["relation"]}

    def confirm_claim_link(self, link_id: str) -> dict:
        return self._update_claim_status(link_id, "confirmed")

    def dismiss_claim_link(self, link_id: str) -> dict:
        return self._update_claim_status(link_id, "dismissed")

    # ------------------------------------------------------ reader path ----

    @staticmethod
    def _reader_path_is_stale(review: dict, draft: dict) -> bool:
        return (review["draft_id"] != draft["id"]
                or review["draft_revision"] != draft["revision"]
                or review["content_hash"] != content_hash(draft["working_content"]))

    def _reader_path_payload(self, review: dict, draft: dict) -> dict:
        stale = self._reader_path_is_stale(review, draft)
        steps = [{
            "id": step["id"], "step_id": step["step_id"],
            "location": {"paragraph_start": step["paragraph_start"],
                         "paragraph_end": step["paragraph_end"]},
            "quote": step["quote"], "primary_function": step["primary_function"],
            "knowledge_gain": step["knowledge_gain"],
            "question_raised": step.get("question_raised"),
            "question_answered": step.get("question_answered"),
        } for step in self.db.q(
            "SELECT * FROM reader_path_steps WHERE review_id=? ORDER BY paragraph_start,rowid",
            (review["id"],))]
        items = {item["issue_id"]: item for item in self.db.q(
            "SELECT * FROM revision_items WHERE review_id=? ORDER BY rowid",
            (review["id"],))}
        issues = []
        for raw in json.loads(review["issues_json"]):
            issue = dict(raw)
            item = items.get(issue["id"])
            if not item:
                continue
            status = ("stale" if stale and item["status"] in ("open", "proposed")
                      else item["status"])
            issue.update({
                "revision_item_id": item["id"], "status": status,
                "severity": item["severity"], "message": item["message"],
                "effect": item["effect"], "goal": item["goal"],
                "quote": item["quote"],
                "location": {"paragraph_start": item["paragraph_start"],
                             "paragraph_end": item["paragraph_end"]},
                "fixable": status == "open",
            })
            issues.append(issue)
        priority = {"major": 0, "moderate": 1, "minor": 2}
        issues.sort(key=lambda item: (
            0 if item["status"] in ("open", "proposed") else 1,
            priority.get(item["severity"], 9), item["location"]["paragraph_start"]))
        return {"id": review["id"], "revision": review["draft_revision"],
                "stale": stale,
                "overview": json.loads(review["summary_json"])["overview"],
                "steps": steps, "issues": issues}

    @tracked("reader_path_review")
    def review_reader_path(self, tid: str) -> dict:
        task = self.get_task(tid)
        draft = self.db.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
        if not draft or not draft["working_content"].strip():
            raise ApiError("NO_DRAFT", "请先生成或导入正文。", 409)
        content = draft["working_content"]
        numbered = [(number, paragraph) for number, paragraph in
                    enumerate(paragraphs(content), 1) if paragraph.strip()]
        if len(content) > READER_PATH_MAX_DRAFT_CHARS:
            raise ApiError("READER_PATH_INPUT_TOO_LARGE",
                           "正文超过 30,000 字符，请缩小检查范围。", 413)
        if len(numbered) > READER_PATH_MAX_PARAGRAPHS:
            raise ApiError("READER_PATH_INPUT_TOO_LARGE",
                           "正文超过 80 个非空段落，请缩小检查范围。", 413)
        if any(len(paragraph) > READER_PATH_MAX_PARAGRAPH_CHARS
               for _, paragraph in numbered):
            raise ApiError("READER_PATH_INPUT_TOO_LARGE",
                           "单个段落超过 10,000 字符，请先拆分段落。", 413)
        digest = content_hash(content)
        CURRENT.get().bind_inputs({"revision": draft["revision"],
                                   "content_hash": digest,
                                   "paragraph_count": len(numbered)})
        ch = CURRENT.get().channel
        callback = _stage_stream(ch.emit, "reader_path_review") if _debug_stream() else None
        ch.emit("stage", {"stage": "reader_path_review"})
        try:
            payload = CURRENT.get().engine.review_reader_path(
                content=content, on_delta=callback)
        except EngineError as exc:
            raise ApiError("READER_PATH_REVIEW_FAILED", str(exc), 500, True) from exc
        except Exception as exc:
            log.exception("ungrouped reader-path review error for %s", tid)
            raise ApiError("READER_PATH_REVIEW_FAILED",
                           f"稿件路径检查失败:{type(exc).__name__} — 请重试。",
                           500, True) from exc
        finally:
            if callback:
                callback.flush()
        if validate_reader_path(payload):
            raise ApiError("READER_PATH_REVIEW_FAILED",
                           "稿件路径检查返回了无法验证的结构，请重试。", 500, True)
        by_number = {number: paragraph for number, paragraph in numbered}
        step_numbers = [step["paragraph"] for step in payload["steps"]]
        if (len(step_numbers) != len(set(step_numbers))
                or set(step_numbers) != set(by_number)
                or any(step["paragraph_quote"] != by_number.get(step["paragraph"])
                       for step in payload["steps"])):
            raise ApiError("READER_PATH_INCOMPLETE",
                           "稿件路径没有完整对应当前正文，请重试。", 500, True)

        review_id, ts = new_id("rpath"), now()
        normalized_issues = []
        for raw in payload["issues"]:
            ps, pe = raw["paragraph_start"], raw["paragraph_end"]
            try:
                region_start, region_end = paragraph_span(content, ps, pe)
            except ApiError:
                continue
            anchor = unique_quote_span(content, raw["quote"], region_start, region_end)
            if not anchor:
                continue
            normalized_issues.append({**raw, "anchor": anchor})

        with self.db.transaction() as tx:
            current = tx.q1("SELECT * FROM drafts WHERE id=?", (draft["id"],))
            if (not current or current["revision"] != draft["revision"]
                    or content_hash(current["working_content"]) != digest):
                raise ApiError("STALE_BASE",
                               "正文在稿件检查期间发生了变化，请重新检查。", 409, True)
            tx.exec(
                "UPDATE revision_items SET status='stale',updated_at=? WHERE review_id IN "
                "(SELECT id FROM reviews WHERE draft_id=? AND analysis_type='reader_path') "
                "AND status IN ('open','proposed')", (ts, draft["id"]))
            issues_for_json = []
            for raw in normalized_issues:
                item_id = new_id("item")
                anchor = raw["anchor"]
                tx.exec(
                    "INSERT INTO revision_items(id,review_id,draft_id,issue_id,base_revision,"
                    "content_hash,paragraph_start,paragraph_end,char_start,char_end,quote,type,"
                    "severity,message,effect,goal,status,created_at,updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?,?)",
                    (item_id, review_id, draft["id"], raw["id"], draft["revision"],
                     digest, raw["paragraph_start"], raw["paragraph_end"],
                     anchor[0], anchor[1], raw["quote"], f"reader_path:{raw['type']}",
                     raw["severity"], raw["message"], raw["effect"], raw["goal"], ts, ts))
                issues_for_json.append({key: raw[key] for key in
                                        ("id", "type", "severity", "message", "effect", "goal")})
            tx.exec(
                "INSERT INTO reviews(id,draft_id,version_id,summary_json,issues_json,created_at,"
                "content_hash,draft_revision,config_json,operation_id,analysis_type)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,'reader_path')",
                (review_id, draft["id"], draft["current_version_id"],
                 json.dumps({"overview": payload["overview"]}, ensure_ascii=False),
                 json.dumps(issues_for_json, ensure_ascii=False), ts, digest,
                 draft["revision"], json.dumps({"analysis_type": "reader_path"}),
                 CURRENT.get().id))
            for step in payload["steps"]:
                char_start, char_end = paragraph_span(
                    content, step["paragraph"], step["paragraph"])
                tx.exec(
                    "INSERT INTO reader_path_steps(id,review_id,draft_id,step_id,base_revision,"
                    "content_hash,paragraph_start,paragraph_end,char_start,char_end,quote,"
                    "primary_function,knowledge_gain,question_raised,question_answered,created_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (new_id("rstep"), review_id, draft["id"], step["id"],
                     draft["revision"], digest, step["paragraph"], step["paragraph"],
                     char_start, char_end, step["paragraph_quote"],
                     step["primary_function"], step["knowledge_gain"],
                     step["question_raised"], step["question_answered"], ts))
        ch.emit("stage_summary", {"stage": "reader_path_review",
                                  "text": f"稿件路径：{len(numbered)} 段 · {len(normalized_issues)} 个问题"})
        ch.emit("done", {"reader_path_review_id": review_id})
        review = self.db.q1("SELECT * FROM reviews WHERE id=?", (review_id,))
        return self._reader_path_payload(review, draft)

    def reader_path_review(self, tid: str) -> dict:
        self.get_task(tid)
        draft = self.db.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
        if not draft:
            raise ApiError("NO_DRAFT", "请先生成或导入正文。", 409)
        review = self.db.q1(
            "SELECT * FROM reviews WHERE draft_id=? AND analysis_type='reader_path' "
            "ORDER BY created_at DESC,rowid DESC LIMIT 1", (draft["id"],))
        if not review:
            return {"id": None, "revision": draft["revision"], "stale": False,
                    "overview": "", "steps": [], "issues": []}
        return self._reader_path_payload(review, draft)

    @staticmethod
    def _invalidate_revision_context(tx, draft_id: str, *, preserve: bool) -> None:
        ts = now()
        tx.exec("UPDATE revision_items SET status='stale',updated_at=? WHERE draft_id=? "
                "AND status IN ('open','proposed')", (ts, draft_id))
        if preserve:
            tx.exec("UPDATE preserved_spans SET status='stale',updated_at=? WHERE draft_id=? "
                    "AND status='active'", (ts, draft_id))

    def list_preserved_spans(self, tid: str) -> dict:
        self.get_task(tid)
        draft = self.db.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
        if not draft:
            return {"draft_id": None, "revision": None, "spans": []}
        digest = content_hash(draft["working_content"])
        spans = self.db.q(
            "SELECT * FROM preserved_spans WHERE draft_id=? ORDER BY char_start,rowid",
            (draft["id"],))
        for span in spans:
            valid = (span["status"] == "active"
                     and span["base_revision"] == draft["revision"]
                     and span["content_hash"] == digest
                     and draft["working_content"][span["char_start"]:span["char_end"]]
                     == span["quote"])
            if not valid and span["status"] == "active":
                span["status"] = "stale"
        return {"draft_id": draft["id"], "revision": draft["revision"], "spans": spans}

    def create_preserved_span(self, tid: str, payload: dict) -> dict:
        selection = payload.get("selection") or {}
        ps, pe = selection.get("paragraph_start"), selection.get("paragraph_end")
        if not (type(ps) is int and type(pe) is int and 1 <= ps <= pe):
            raise ApiError("VALIDATION", "Select one or more complete paragraphs first.")
        self.get_task(tid)
        with self.db.transaction() as tx:
            draft = tx.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
            if not draft:
                raise ApiError("NO_DRAFT", "Generate a draft first.", 409)
            self._check_revision(draft, payload.get("expected_revision"))
            char_start, char_end = paragraph_span(draft["working_content"], ps, pe)
            quote = draft["working_content"][char_start:char_end]
            if not quote.strip():
                raise ApiError("VALIDATION", "An empty paragraph cannot be preserved.")
            existing = tx.q1(
                "SELECT * FROM preserved_spans WHERE draft_id=? AND status='active' "
                "AND char_start=? AND char_end=? AND quote=?",
                (draft["id"], char_start, char_end, quote))
            if existing:
                return {**existing, "deduped": True}
            sid, ts = new_id("keep"), now()
            digest = content_hash(draft["working_content"])
            tx.exec(
                "INSERT INTO preserved_spans(id,draft_id,base_revision,content_hash,"
                "paragraph_start,paragraph_end,char_start,char_end,quote,status,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,'active',?,?)",
                (sid, draft["id"], draft["revision"], digest, ps, pe,
                 char_start, char_end, quote, ts, ts))
            return tx.q1("SELECT * FROM preserved_spans WHERE id=?", (sid,))

    def delete_preserved_span(self, span_id: str) -> dict:
        with self.db.transaction() as tx:
            span = tx.q1("SELECT * FROM preserved_spans WHERE id=?", (span_id,))
            if not span:
                raise ApiError("NOT_FOUND", "Preserved passage not found.", 404)
            tx.exec("DELETE FROM preserved_spans WHERE id=?", (span_id,))
        return {"preserved_span_id": span_id, "status": "removed"}

    @staticmethod
    def _rebase_preserved_spans(spans: list[dict], content: str,
                                char_start: int, char_end: int,
                                after_text: str, revision: int) -> tuple[str, list[tuple[dict, int, int]]]:
        candidate = content[:char_start] + after_text + content[char_end:]
        delta = len(after_text) - (char_end - char_start)
        rebased = []
        digest = content_hash(content)
        for span in spans:
            if (span["status"] != "active" or span["base_revision"] != revision
                    or span["content_hash"] != digest
                    or content[span["char_start"]:span["char_end"]] != span["quote"]):
                raise ApiError("PRESERVED_TEXT_CONFLICT",
                               "保留片段已失效，请重新载入后再修改。", 409, True)
            if span["char_end"] <= char_start:
                new_start = span["char_start"]
            elif span["char_start"] >= char_end:
                new_start = span["char_start"] + delta
            else:
                occurrences = [m.start() for m in re.finditer(
                    re.escape(span["quote"]), candidate)]
                if len(occurrences) != 1:
                    raise ApiError("PRESERVED_TEXT_CONFLICT",
                                   "这次修改会改变已保留的原文，请先调整选区或取消保留。",
                                   422, True)
                new_start = occurrences[0]
            new_end = new_start + len(span["quote"])
            if candidate[new_start:new_end] != span["quote"]:
                raise ApiError("PRESERVED_TEXT_CONFLICT",
                               "这次修改会改变已保留的原文，请先调整选区或取消保留。",
                               422, True)
            rebased.append((span, new_start, new_end))
        return candidate, rebased

    def dismiss_revision_item(self, item_id: str) -> dict:
        with self.db.transaction() as tx:
            item = tx.q1("SELECT * FROM revision_items WHERE id=?", (item_id,))
            if not item:
                raise ApiError("NOT_FOUND", "Revision item not found.", 404)
            if item["status"] != "open":
                raise ApiError("STALE_REVISION_ITEM", "This revision item is no longer open.", 409)
            tx.exec("UPDATE revision_items SET status='dismissed',updated_at=? WHERE id=?",
                    (now(), item_id))
        return {"revision_item_id": item_id, "status": "dismissed"}

    # ------------------------------------------------------------- patch ----

    @tracked("patch")
    def propose_patch(self, tid: str, payload: dict) -> dict:
        base_version_id = payload.get("base_version_id")
        selection = payload.get("selection") or {}
        ps, pe = selection.get("paragraph_start"), selection.get("paragraph_end")
        if not (type(ps) is int and type(pe) is int and 1 <= ps <= pe):
            raise ApiError("VALIDATION", "Select a passage first.")
        task = self.get_task(tid)
        draft = self.db.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
        if not draft:
            raise ApiError("NO_DRAFT", "Generate a draft first.", 409)
        if base_version_id and base_version_id != draft["current_version_id"]:
            raise ApiError("STALE_BASE",
                           "The draft changed since this revision was requested.",
                           409, retryable=True)
        self._check_revision(draft, payload.get("expected_revision"))
        revision_item = None
        revision_item_id = payload.get("revision_item_id")
        claim_link = None
        claim_link_id = payload.get("claim_link_id")
        if revision_item_id and claim_link_id:
            raise ApiError("VALIDATION", "一次修改只能关联一个检查项。")
        if revision_item_id:
            revision_item = self.db.q1(
                "SELECT * FROM revision_items WHERE id=? AND draft_id=?",
                (revision_item_id, draft["id"]))
            if not revision_item:
                raise ApiError("NOT_FOUND", "Revision item not found.", 404)
            if revision_item["status"] != "open":
                raise ApiError("STALE_REVISION_ITEM", "This revision item is no longer open.", 409)
            if payload.get("review_id") and payload["review_id"] != revision_item["review_id"]:
                raise ApiError("WRONG_REVIEW", "Revision item belongs to another review.", 409)
            if (ps, pe) != (revision_item["paragraph_start"], revision_item["paragraph_end"]):
                raise ApiError("INVALID_SELECTION", "Use the passage anchored by this revision item.")
            if self.db.q1(
                    "SELECT id FROM revision_items WHERE review_id=? AND status='proposed' LIMIT 1",
                    (revision_item["review_id"],)):
                raise ApiError("PATCH_ALREADY_PROPOSED",
                               "Resolve the current proposal before starting another work item.", 409)
        if claim_link_id:
            claim_link = self.db.q1(
                "SELECT * FROM claim_links WHERE id=? AND draft_id=?",
                (claim_link_id, draft["id"]))
            if not claim_link:
                raise ApiError("NOT_FOUND", "依据卡不存在。", 404)
            check = self.db.q1("SELECT * FROM claim_checks WHERE id=?",
                               (claim_link["check_id"],))
            if (not check or check["task_id"] != tid
                    or self._evidence_is_stale(check, task, draft)):
                raise ApiError("STALE_EVIDENCE_CHECK",
                               "正文或素材已改变，请重新检查。", 409, True)
            if claim_link["user_status"] == "dismissed":
                raise ApiError("CLAIM_LINK_DISMISSED", "这一依据卡已被忽略。", 409)
            if claim_link.get("patch_id"):
                linked_patch = self.db.q1(
                    "SELECT status FROM proposed_patches WHERE id=?",
                    (claim_link["patch_id"],))
                if linked_patch and linked_patch["status"] == "proposed":
                    raise ApiError("PATCH_ALREADY_PROPOSED",
                                   "请先处理这张依据卡的当前提案。", 409)
            if (ps, pe) != (claim_link["paragraph_start"],
                            claim_link["paragraph_end"]):
                raise ApiError("INVALID_SELECTION", "请使用依据卡定位的正文段落。")
        instruction = (payload.get("instruction")
                       or (revision_item or {}).get("goal")
                       or (claim_link or {}).get("revision_goal") or "").strip()
        if not instruction:
            raise ApiError("VALIDATION", "Tell me how to revise the passage.")
        if payload.get("review_id"):
            row = self.db.q1("SELECT * FROM reviews WHERE id=? AND draft_id=?",
                             (payload["review_id"], draft["id"]))
            stale = (not row or
                     (row["analysis_type"] == "writing"
                      and self._review_payload(row, task, draft)["stale"]) or
                     (row["analysis_type"] == "reader_path"
                      and self._reader_path_is_stale(row, draft)))
            if stale:
                raise ApiError("STALE_REVIEW", "正文或目标已改变，请重新检查后再修改。", 409, True)
        content = draft["working_content"]
        char_start, char_end = paragraph_span(content, ps, pe)
        before_text = content[char_start:char_end]
        digest = content_hash(content)
        if revision_item and (
                revision_item["base_revision"] != draft["revision"]
                or revision_item["content_hash"] != digest
                or revision_item["char_start"] != char_start
                or revision_item["char_end"] != char_end
                or revision_item["quote"] != before_text):
            raise ApiError("STALE_REVISION_ITEM",
                           "The anchored passage changed; run review again.", 409, True)
        if claim_link and (
                claim_link["draft_char_start"] < char_start
                or claim_link["draft_char_end"] > char_end
                or content[claim_link["draft_char_start"]:
                           claim_link["draft_char_end"]] != claim_link["draft_quote"]):
            raise ApiError("STALE_EVIDENCE_CHECK",
                           "依据卡定位的正文已经改变，请重新检查。", 409, True)
        locks = payload.get("locks") or task["config"].get("locks") or {}
        CURRENT.get().bind_inputs({
            "content_hash": hashlib.sha256(content.encode()).hexdigest(),
            "revision": draft["revision"], "selection": selection,
            "instruction": instruction, "locks": locks,
            "engine": CURRENT.get().snapshot})
        try:
            after_text = CURRENT.get().engine.patch(
                content=content, before_text=before_text,
                instruction=instruction, locks=locks,
                config=self._config_dict(task))
        except LockConflict as exc:
            # fail safely: no patch row, draft untouched
            raise ApiError("LOCK_CONFLICT", str(exc), 422, retryable=True) from exc
        except EngineError as exc:
            raise ApiError("PATCH_FAILED", str(exc), 500, retryable=True) from exc
        active_spans = self.db.q(
            "SELECT * FROM preserved_spans WHERE draft_id=? AND status='active' ORDER BY rowid",
            (draft["id"],))
        self._rebase_preserved_spans(
            active_spans, content, char_start, char_end, after_text, draft["revision"])
        CURRENT.get().record("stage_result", "revision", data={
            "paragraph_count": pe - ps + 1})
        pid = new_id("patch")
        ts = now()
        selection_json = json.dumps(
            {"paragraph_start": ps, "paragraph_end": pe,
             "char_start": char_start, "char_end": char_end},
            ensure_ascii=False)
        with self.db.transaction() as tx:
            current = tx.q1("SELECT * FROM drafts WHERE id=?", (draft["id"],))
            if (not current or current["revision"] != draft["revision"]
                    or current["current_version_id"] != draft["current_version_id"]
                    or current["working_content"] != content):
                raise ApiError("STALE_BASE", "正文已改变，请重新提出修改。", 409, True)
            spans = tx.q(
                "SELECT * FROM preserved_spans WHERE draft_id=? AND status='active' ORDER BY rowid",
                (draft["id"],))
            self._rebase_preserved_spans(
                spans, content, char_start, char_end, after_text, draft["revision"])
            if revision_item_id:
                live = tx.q1("SELECT * FROM revision_items WHERE id=?", (revision_item_id,))
                if (not live or live["status"] != "open"
                        or live["base_revision"] != draft["revision"]
                        or live["content_hash"] != digest):
                    raise ApiError("STALE_REVISION_ITEM",
                                   "This revision item changed; reload and try again.", 409, True)
                if tx.q1("SELECT id FROM revision_items WHERE review_id=? "
                         "AND status='proposed' LIMIT 1", (live["review_id"],)):
                    raise ApiError("PATCH_ALREADY_PROPOSED",
                                   "Resolve the current proposal before starting another work item.", 409)
            if claim_link_id:
                live_link = tx.q1("SELECT * FROM claim_links WHERE id=?", (claim_link_id,))
                live_check = tx.q1("SELECT * FROM claim_checks WHERE id=?",
                                   ((live_link or {}).get("check_id", ""),))
                if (not live_link or not live_check
                        or live_link["user_status"] == "dismissed"
                        or live_link.get("patch_id")
                        or live_check["draft_revision"] != draft["revision"]
                        or live_check["content_hash"] != digest
                        or json.loads(live_check["sources_json"])
                           != self._source_snapshot(self.get_task(tid))):
                    raise ApiError("STALE_EVIDENCE_CHECK",
                                   "依据卡已经改变，请重新载入。", 409, True)
            tx.exec(
                "INSERT INTO proposed_patches(id,draft_id,base_version_id,selection_json,instruction,"
                "before_text,after_text,status,locks_json,error,created_at,base_revision,"
                "task_locks_json,revision_item_id,claim_link_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, draft["id"], draft["current_version_id"], selection_json,
                 instruction, before_text, after_text, "proposed",
                 json.dumps(locks, ensure_ascii=False), None, ts, draft["revision"],
                 json.dumps(task["config"].get("locks") or {}, ensure_ascii=False),
                 revision_item_id, claim_link_id))
            if revision_item_id:
                tx.exec("UPDATE revision_items SET status='proposed',patch_id=?,updated_at=? "
                        "WHERE id=?", (pid, ts, revision_item_id))
            if claim_link_id:
                tx.exec("UPDATE claim_links SET patch_id=?,updated_at=? WHERE id=?",
                        (pid, ts, claim_link_id))
        return {"patch_id": pid, "before": before_text, "after": after_text,
                "status": "proposed", "revision_item_id": revision_item_id,
                "claim_link_id": claim_link_id}

    @staticmethod
    def _check_revision(draft: dict, expected) -> None:
        if type(expected) is not int or expected < 0:
            raise ApiError("REVISION_REQUIRED", "页面需要刷新后再保存，请先保留本地输入。", 428)
        if draft["revision"] != expected:
            raise ApiError("STALE_BASE", "正文已在其他操作中改变；请保留本地修改并重新载入。", 409,
                           retryable=True)

    @staticmethod
    def _version_write(tx, draft, content, source_type, *, instruction=None,
                       plan_id=None, restored_from=None):
        vid, ts = new_id("ver"), now()
        tx.exec("INSERT INTO versions(id,draft_id,parent_version_id,content,source_type,"
                "instruction,created_at,engine_plan_id,restore_source_version_id)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (vid, draft["id"], draft["current_version_id"], content, source_type,
                 instruction, ts, plan_id, restored_from))
        tx.exec("UPDATE drafts SET current_version_id=?,working_content=?,updated_at=?,"
                "revision=revision+1 WHERE id=?",
                (vid, content, ts, draft["id"]))
        return vid, draft["revision"] + 1

    @staticmethod
    def _draft_plan_id(tx, draft):
        version = tx.q1("SELECT engine_plan_id FROM versions WHERE id=?",
                         (draft["current_version_id"],))
        return (version or {}).get("engine_plan_id")

    def _preserve_working_copy(self, tx, draft):
        current = tx.q1("SELECT content FROM versions WHERE id=?", (draft["current_version_id"],))
        if draft["current_version_id"] and (not current or current["content"] != draft["working_content"]):
            vid, revision = self._version_write(
                tx, draft, draft["working_content"], "manual_checkpoint",
                plan_id=self._draft_plan_id(tx, draft))
            return {**draft, "current_version_id": vid, "revision": revision}
        return draft

    def accept_patch(self, patch_id: str) -> dict:
        with self.db.transaction() as tx:
            patch = tx.q1("SELECT * FROM proposed_patches WHERE id=?", (patch_id,))
            if not patch:
                raise ApiError("NOT_FOUND", "Patch not found.", 404)
            if patch["status"] != "proposed":
                raise ApiError("STALE_PATCH", "This patch was already resolved.", 409)
            item = None
            if patch.get("revision_item_id"):
                item = tx.q1("SELECT * FROM revision_items WHERE id=?",
                              (patch["revision_item_id"],))
                if (not item or item["status"] != "proposed"
                        or item["patch_id"] != patch_id):
                    raise ApiError("STALE_REVISION_ITEM",
                                   "This work item is no longer current.", 409, True)
            claim_link = None
            if patch.get("claim_link_id"):
                claim_link = tx.q1("SELECT * FROM claim_links WHERE id=?",
                                   (patch["claim_link_id"],))
                check = tx.q1("SELECT * FROM claim_checks WHERE id=?",
                              ((claim_link or {}).get("check_id", ""),))
                if (not claim_link or claim_link.get("patch_id") != patch_id
                        or not check):
                    raise ApiError("STALE_EVIDENCE_CHECK",
                                   "这张依据卡不再关联当前提案。", 409, True)
            draft = tx.q1("SELECT * FROM drafts WHERE id=?", (patch["draft_id"],))
            if draft["current_version_id"] != patch["base_version_id"]:
                raise ApiError("STALE_BASE", "正文版本已改变，请重新提出修改。", 409, True)
            self._check_revision(draft, patch["base_revision"])
            if claim_link:
                task = self.get_task(check["task_id"])
                if self._evidence_is_stale(check, task, draft):
                    raise ApiError("STALE_EVIDENCE_CHECK",
                                   "正文或素材已改变，请重新检查。", 409, True)
            config = tx.q1("SELECT locks_json FROM writing_configs WHERE task_id=?", (draft["task_id"],))
            if json.loads(patch["task_locks_json"] or "null") != json.loads(config["locks_json"] or "{}"):
                raise ApiError("LOCK_CONFLICT", "保护项已改变，请按当前保护项重新提出修改。", 409, True)
            sel = json.loads(patch["selection_json"])
            content = draft["working_content"]
            if content[sel["char_start"]:sel["char_end"]] != patch["before_text"]:
                raise ApiError("STALE_BASE", "The selected passage changed.", 409, True)
            spans = tx.q(
                "SELECT * FROM preserved_spans WHERE draft_id=? AND status='active' ORDER BY rowid",
                (draft["id"],))
            new_content, rebased = self._rebase_preserved_spans(
                spans, content, sel["char_start"], sel["char_end"],
                patch["after_text"], draft["revision"])
            draft = self._preserve_working_copy(tx, draft)
            vid, revision = self._version_write(
                tx, draft, new_content, "patch", instruction=patch["instruction"],
                plan_id=self._draft_plan_id(tx, draft))
            digest = content_hash(new_content)
            for span, new_start, new_end in rebased:
                ps, pe = paragraph_range_for_span(new_content, new_start, new_end)
                tx.exec(
                    "UPDATE preserved_spans SET base_revision=?,content_hash=?,paragraph_start=?,"
                    "paragraph_end=?,char_start=?,char_end=?,updated_at=? WHERE id=?",
                    (revision, digest, ps, pe, new_start, new_end, now(), span["id"]))
            tx.exec("UPDATE proposed_patches SET status='accepted',accepted_version_id=? WHERE id=?",
                    (vid, patch_id))
            if item:
                ts = now()
                tx.exec("UPDATE revision_items SET status='resolved',updated_at=? WHERE id=?",
                        (ts, item["id"]))
                tx.exec("UPDATE revision_items SET status='stale',updated_at=? WHERE review_id=? "
                        "AND id<>? AND status IN ('open','proposed')",
                        (ts, item["review_id"], item["id"]))
            else:
                self._invalidate_revision_context(tx, draft["id"], preserve=False)
        return {"patch_id": patch_id, "version_id": vid, "revision": revision,
                "status": "accepted", "content": new_content}

    def reject_patch(self, patch_id: str) -> dict:
        with self.db.transaction() as tx:
            patch = tx.q1("SELECT * FROM proposed_patches WHERE id=?", (patch_id,))
            if not patch:
                raise ApiError("NOT_FOUND", "Patch not found.", 404)
            if patch["status"] != "proposed":
                raise ApiError("STALE_PATCH", "This patch was already resolved.", 409)
            tx.exec("UPDATE proposed_patches SET status='rejected' WHERE id=?", (patch_id,))
            if patch.get("revision_item_id"):
                tx.exec("UPDATE revision_items SET status='open',patch_id=NULL,updated_at=? "
                        "WHERE id=? AND status='proposed' AND patch_id=?",
                        (now(), patch["revision_item_id"], patch_id))
            if patch.get("claim_link_id"):
                tx.exec("UPDATE claim_links SET patch_id=NULL,updated_at=? "
                        "WHERE id=? AND patch_id=?",
                        (now(), patch["claim_link_id"], patch_id))
        return {"patch_id": patch_id, "status": "rejected"}

    # ---------------------------------------------------------- versions ----

    def list_versions(self, draft_id: str) -> list[dict]:
        rows = self.db.q(
            "SELECT id,draft_id,parent_version_id,source_type,instruction,created_at,"
            "engine_plan_id,restore_source_version_id"
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

    def export_task(self, tid: str, format_: str, expected_revision=None,
                    include_title=True):
        if format_ not in ("md", "txt") or type(include_title) is not bool:
            raise ApiError("VALIDATION", "Export format or options are invalid.")
        # Validate and copy the exact content/revision pair inside one database
        # critical section, so a concurrent autosave cannot slip between them.
        with self.db.transaction() as tx:
            task = tx.q1("SELECT id,title FROM tasks WHERE id=?", (tid,))
            if not task:
                raise ApiError("NOT_FOUND", "Task not found.", 404)
            draft = tx.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
            if not draft:
                raise ApiError("NO_DRAFT", "Generate a draft before export.", 409)
            self._check_revision(draft, expected_revision)
            return build_export(
                content=draft["working_content"], title=task["title"],
                identifier=tid, format_=format_, include_title=include_title)

    def export_version(self, version_id: str, format_: str, include_title=True):
        if format_ not in ("md", "txt") or type(include_title) is not bool:
            raise ApiError("VALIDATION", "Export format or options are invalid.")
        row = self.db.q1(
            "SELECT v.content,t.title,t.id AS task_id FROM versions v "
            "JOIN drafts d ON d.id=v.draft_id JOIN tasks t ON t.id=d.task_id "
            "WHERE v.id=?", (version_id,))
        if not row:
            raise ApiError("NOT_FOUND", "Version not found.", 404)
        return build_export(
            content=row["content"], title=row["title"], identifier=version_id,
            format_=format_, include_title=include_title)

    def create_workspace_backup(self):
        try:
            return build_workspace_backup(self.db)
        except BackupError as exc:
            raise ApiError("BACKUP_FAILED", str(exc), 409) from exc

    def inspect_workspace_backup(self, content: bytes) -> dict:
        try:
            return inspect_workspace_backup(content).summary
        except BackupError as exc:
            raise ApiError("INVALID_BACKUP", str(exc), 400) from exc

    def restore_workspace_backup(self, content: bytes) -> dict:
        try:
            return restore_workspace_backup(content, self.restore_root)
        except BackupError as exc:
            raise ApiError("INVALID_BACKUP", str(exc), 400) from exc
        except OSError as exc:
            log.exception("Independent workspace restore failed")
            raise ApiError("RESTORE_FAILED", "Could not create the restored workspace.",
                           500, retryable=True) from exc

    def restore_version(self, version_id: str, expected_revision=None) -> dict:
        with self.db.transaction() as tx:
            version = tx.q1("SELECT * FROM versions WHERE id=?", (version_id,))
            if not version:
                raise ApiError("NOT_FOUND", "Version not found.", 404)
            draft = tx.q1("SELECT * FROM drafts WHERE id=?", (version["draft_id"],))
            self._check_revision(draft, expected_revision)
            draft = self._preserve_working_copy(tx, draft)
            rid, revision = self._version_write(
                tx, draft, version["content"], "restore",
                plan_id=version["engine_plan_id"], restored_from=version_id)
            self._invalidate_revision_context(tx, draft["id"], preserve=True)
        return {"version_id": rid, "restored_from": version_id,
                "content": version["content"], "revision": revision}

    def checkpoint(self, tid: str, expected_revision=None) -> dict:
        self.get_task(tid)
        with self.db.transaction() as tx:
            draft = tx.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
            if not draft:
                raise ApiError("NO_DRAFT", "Generate a draft first.", 409)
            self._check_revision(draft, expected_revision)
            cur = tx.q1("SELECT content FROM versions WHERE id=?", (draft["current_version_id"],))
            if cur and cur["content"] == draft["working_content"]:
                return {"version_id": draft["current_version_id"], "revision": draft["revision"],
                        "deduped": True}
            vid, revision = self._version_write(
                tx, draft, draft["working_content"], "manual_checkpoint",
                plan_id=self._draft_plan_id(tx, draft))
        return {"version_id": vid, "revision": revision}

    def autosave(self, draft_id: str, working_content: str, expected_revision=None) -> dict:
        with self.db.transaction() as tx:
            draft = tx.q1("SELECT * FROM drafts WHERE id=?", (draft_id,))
            if not draft:
                raise ApiError("NOT_FOUND", "Draft not found.", 404)
            self._check_revision(draft, expected_revision)
            revision = draft["revision"]
            if working_content != draft["working_content"]:
                tx.exec("UPDATE drafts SET working_content=?,updated_at=?,revision=revision+1 WHERE id=?",
                        (working_content, now(), draft_id))
                self._invalidate_revision_context(tx, draft_id, preserve=True)
                revision += 1
        return {"draft_id": draft_id, "saved_at": now(), "revision": revision}

    # ------------------------------------------------------ retry paths ----

    @tracked("rediscover_angle")
    def rediscover_angle(self, tid: str, payload: dict | None = None) -> dict:
        """Try Another Angle: rerun Meaning Discovery/selection, then generate.

        Distinct code path from regenerate(): discovery runs again with an
        avoid-list of every previously selected angle.
        """
        task = self._generation_task(tid, payload or {})
        if task.get("input_mode") != "topic_only":
            raise ApiError("VALIDATION",
                           "Angle retry is only for idea-based tasks.", 409)
        avoid = self._past_angle_labels(tid)
        ch = CURRENT.get().channel
        ch.emit("stage", {"stage": "queued"})
        try:
            discovery = self.discover(task, avoid=avoid, emit=ch.emit)
            material = self._material(task) or task["topic"]
            return self._generate_with(task, meaning=discovery, material=material)
        finally:
            ch.close()

    @tracked("regenerate")
    def regenerate(self, tid: str, payload: dict) -> dict:
        """Rewrite Same Angle: preserve the selected meaning, rerun downstream."""
        task = self._generation_task(tid, payload)
        if task.get("input_mode") != "topic_only":
            raise ApiError("VALIDATION",
                           "This rewrite applies only to idea-based tasks.", 409)
        preserve = payload.get("preserve_angle", True)
        if preserve is not True:
            raise ApiError("VALIDATION", "preserve_angle must be true.")
        discovery = self._current_discovery(tid)
        if not discovery:
            raise ApiError("NO_MEANING",
                           "Generate once first so an angle can be preserved.", 409)
        ch = CURRENT.get().channel
        ch.emit("stage", {"stage": "queued"})
        ch.emit("angle", meaning_schema.product_safe_summary(discovery["data"]))
        try:
            material = self._material(task) or task["topic"]
            plan = self._resumable_plan(task, discovery)
            return self._generate_with(task, meaning=discovery,
                                       material=material, plan=plan)
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
        meaning = self._current_discovery(tid)
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
        object_name = str(payload.get("object") or "").strip() or None
        # "sub" kept as a legacy alias for tension (v1 taxonomy param name).
        tension = str(payload.get("tension")
                      or payload.get("sub") or "").strip() or None
        known_domains = {d["id"] for d in taxonomy["domains"]}
        known_objects = {o for g in taxonomy.get("objects", [])
                         for o in g["items"]}
        known_tensions = {t["id"] for t in taxonomy["tensions"]}
        if domain is not None and domain not in known_domains:
            raise ApiError("VALIDATION", f"unknown domain: {domain}")
        if object_name is not None and object_name not in known_objects:
            raise ApiError("VALIDATION", f"unknown object: {object_name}")
        if tension is not None and tension not in known_tensions:
            raise ApiError("VALIDATION", f"unknown tension: {tension}")
        avoid = [str(x).strip() for x in payload.get("avoid") or []
                 if str(x).strip()]
        count = payload.get("count", 8)
        if isinstance(count, bool) or not isinstance(count, int) \
                or not 3 <= count <= 12:
            raise ApiError("VALIDATION", "count must be an integer in 3..12")
        hint = str(payload.get("hint") or "").strip() or None
        if hint and len(hint) > 100:
            raise ApiError("VALIDATION", "hint must be at most 100 characters")
        seed = str(payload.get("seed") or "").strip() or None
        if seed and len(seed) > 200:
            raise ApiError("VALIDATION", "seed must be at most 200 characters")
        try:
            data = self.engine.suggest_topics(domain=domain,
                                              object_name=object_name,
                                              tension=tension,
                                              avoid=avoid, config=None,
                                              count=count, hint=hint,
                                              seed=seed)
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
        discovery = self._current_discovery(tid)
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
        for k in ("timeout_seconds", "writer_temperature"):
            if k in patch and patch[k] not in (None, ""):
                try:
                    patch[k] = float(patch[k])
                except (TypeError, ValueError):
                    raise ApiError("VALIDATION", f"{k} must be a number.")
        if "writer_temperature" in patch and patch["writer_temperature"] is not None \
                and not 0 <= patch["writer_temperature"] <= 2:
            raise ApiError("VALIDATION", "writer_temperature must be within 0-2.")
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
        plan = self._plan_for_draft(draft)
        if not plan:
            return {"beats": [], "mapping": "unknown", "revision": draft["revision"]}
        beats = self.engine.writing_map(plan=plan, content=draft["working_content"])
        return {"beats": beats, "mapping": "heuristic", "revision": draft["revision"]}


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
