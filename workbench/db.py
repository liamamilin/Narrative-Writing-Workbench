"""SQLite persistence for the Workbench (product/06_DATA_MODEL.md)."""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "workbench" / "workbench.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources(
  id TEXT PRIMARY KEY, project_id TEXT, title TEXT NOT NULL,
  type TEXT NOT NULL CHECK(type IN ('pasted_text','uploaded_file','note')),
  content TEXT NOT NULL DEFAULT '', metadata_json TEXT DEFAULT '{}',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(
  id TEXT PRIMARY KEY, project_id TEXT, type TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '', instruction TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK(status IN ('draft','generating','ready','failed','done')),
  expected_language TEXT DEFAULT 'auto',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  input_mode TEXT NOT NULL DEFAULT 'source_grounded'
    CHECK(input_mode IN ('topic_only','source_grounded','draft_revision')),
  topic TEXT DEFAULT '', writing_mode TEXT DEFAULT '',
  angle_mode TEXT DEFAULT 'auto', custom_angle TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS task_sources(
  task_id TEXT NOT NULL, source_id TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'primary'
    CHECK(role IN ('primary','context','reference')),
  PRIMARY KEY(task_id, source_id));
CREATE TABLE IF NOT EXISTS writing_configs(
  task_id TEXT PRIMARY KEY,
  immersion TEXT, explicitness TEXT, intensity TEXT,
  target_length INTEGER, locks_json TEXT DEFAULT '{}',
  constraints_json TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS engine_plans(
  id TEXT PRIMARY KEY, task_id TEXT NOT NULL, schema_version TEXT DEFAULT '1',
  data_json TEXT NOT NULL, created_at TEXT NOT NULL,
  meaning_id TEXT, inputs_json TEXT);
CREATE TABLE IF NOT EXISTS meaning_discoveries(
  id TEXT PRIMARY KEY, task_id TEXT NOT NULL, topic TEXT NOT NULL,
  selected_angle_id TEXT, status TEXT NOT NULL DEFAULT 'ready'
    CHECK(status IN ('ready','failed')),
  data_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS drafts(
  id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
  current_version_id TEXT, working_content TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS versions(
  id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, parent_version_id TEXT,
  content TEXT NOT NULL,
  source_type TEXT NOT NULL
    CHECK(source_type IN ('generation','patch','manual_checkpoint','restore')),
  instruction TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS proposed_patches(
  id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, base_version_id TEXT NOT NULL,
  selection_json TEXT NOT NULL, instruction TEXT NOT NULL,
  before_text TEXT NOT NULL, after_text TEXT, status TEXT NOT NULL
    CHECK(status IN ('proposed','accepted','rejected')),
  locks_json TEXT DEFAULT '{}', error TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reviews(
  id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, version_id TEXT NOT NULL,
  summary_json TEXT NOT NULL, issues_json TEXT NOT NULL,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS writing_operations(
  id TEXT PRIMARY KEY, task_id TEXT NOT NULL, kind TEXT NOT NULL,
  process_id TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed','interrupted')),
  stage TEXT, started_at TEXT NOT NULL, finished_at TEXT, elapsed_ms INTEGER,
  input_fingerprint TEXT, snapshot_json TEXT NOT NULL DEFAULT '{}',
  retry_of TEXT, error_code TEXT, result_json TEXT, usage_json TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_running_operation ON writing_operations(task_id) WHERE status='running';
CREATE TABLE IF NOT EXISTS operation_events(
  operation_id TEXT NOT NULL, seq INTEGER NOT NULL, kind TEXT NOT NULL,
  data_json TEXT NOT NULL, elapsed_ms INTEGER NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(operation_id,seq));
CREATE TABLE IF NOT EXISTS operation_records(
  id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, category TEXT NOT NULL,
  name TEXT NOT NULL, status TEXT NOT NULL, data_json TEXT NOT NULL DEFAULT '{}',
  elapsed_ms INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS operation_records_operation ON operation_records(operation_id);
CREATE TABLE IF NOT EXISTS generation_results(
  id TEXT PRIMARY KEY, task_id TEXT NOT NULL, engine_plan_id TEXT,
  content TEXT NOT NULL, accepted_version_id TEXT, created_at TEXT NOT NULL);
"""

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Transaction:
    """Queries on a transaction-owned connection; never commits implicitly."""

    def __init__(self, conn):
        self.conn = conn

    def exec(self, sql: str, params: tuple = ()):
        return self.conn.execute(sql, params)

    def q(self, sql: str, params: tuple = ()):
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def q1(self, sql: str, params: tuple = ()):
        rows = self.q(sql, params)
        return rows[0] if rows else None


class Database:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or os.environ.get("WORKBENCH_DB", DEFAULT_DB))
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.migration_backup = None
        with self._lock:
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            if version > 3:
                self.conn.close()
                raise RuntimeError("Database schema is newer than this Workbench; use a compatible version.")
            if version < 3 and self.path != ":memory:" and self.conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone():
                self.migration_backup = f"{self.path}.pre-v3-{new_id('backup')}.sqlite3"
                with sqlite3.connect(self.migration_backup) as backup:
                    self.conn.backup(backup)
            try:
                # executescript normally commits implicitly; put BEGIN inside it.
                self.conn.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)
                self._migrate()
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                self.conn.close()
                raise

    def _migrate(self):
        """Idempotent additive migration for pre-V0.1 databases."""
        def cols(table):
            return {r["name"] for r in self.conn.execute(
                f"PRAGMA table_info({table})").fetchall()}
        have = cols("tasks")
        for name, ddl in [
            ("input_mode", "TEXT NOT NULL DEFAULT 'source_grounded'"),
            ("topic", "TEXT DEFAULT ''"),
            ("writing_mode", "TEXT DEFAULT ''"),
            ("angle_mode", "TEXT DEFAULT 'auto'"),
            ("custom_angle", "TEXT DEFAULT ''"),
        ]:
            if name not in have:
                self.conn.execute(
                    f"ALTER TABLE tasks ADD COLUMN {name} {ddl}")
        if "meaning_id" not in cols("engine_plans"):
            self.conn.execute(
                "ALTER TABLE engine_plans ADD COLUMN meaning_id TEXT")
        if "inputs_json" not in cols("engine_plans"):
            self.conn.execute(
                "ALTER TABLE engine_plans ADD COLUMN inputs_json TEXT")

        # Additive migration: old versions/patches have unknown provenance.
        additions = {
            "meaning_discoveries": [("operation_id", "TEXT"), ("inputs_json", "TEXT")],
            "engine_plans": [("operation_id", "TEXT")],
            "generation_results": [("operation_id", "TEXT")],
            "drafts": [("revision", "INTEGER NOT NULL DEFAULT 0")],
            "versions": [("engine_plan_id", "TEXT"),
                         ("restore_source_version_id", "TEXT")],
            "proposed_patches": [("base_revision", "INTEGER"),
                                 ("accepted_version_id", "TEXT"),
                                 ("task_locks_json", "TEXT")],
            "reviews": [("content_hash", "TEXT"), ("draft_revision", "INTEGER"),
                        ("config_json", "TEXT"), ("operation_id", "TEXT")],
        }
        for table, fields in additions.items():
            existing = cols(table)
            for name, ddl in fields:
                if name not in existing:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        # Old draft-revision entry stored the original only as a primary Source.
        # Recover only an unambiguous, nonempty original, and never replace a draft.
        originals = self.conn.execute(
            "SELECT t.id,s.content FROM tasks t JOIN task_sources ts ON ts.task_id=t.id "
            "JOIN sources s ON s.id=ts.source_id WHERE t.input_mode='draft_revision' "
            "AND ts.role='primary' AND NOT EXISTS(SELECT 1 FROM drafts d WHERE d.task_id=t.id) "
            "AND (SELECT count(*) FROM task_sources p WHERE p.task_id=t.id AND p.role='primary')=1").fetchall()
        for original in originals:
            if not original["content"].strip():
                continue
            did, vid, at = new_id("draft"), new_id("v"), datetime.now(timezone.utc).isoformat()
            self.conn.execute("INSERT INTO drafts(id,task_id,current_version_id,working_content,updated_at,revision) VALUES(?,?,?,?,?,1)",
                              (did, original["id"], vid, original["content"], at))
            self.conn.execute("INSERT INTO versions(id,draft_id,content,source_type,instruction,created_at) VALUES(?,?,?,'manual_checkpoint',?,?)",
                              (vid, did, original["content"], "恢复旧稿入口的原稿", at))
            self.conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (original["id"],))
        self.conn.execute("CREATE INDEX IF NOT EXISTS versions_plan ON versions(engine_plan_id)")
        self.conn.execute("PRAGMA user_version=3")

    # -- tiny helpers ----------------------------------------------------

    def exec(self, sql: str, params: tuple = ()):
        with self.transaction() as tx:
            return tx.exec(sql, params)

    @contextmanager
    def transaction(self):
        """Serialize a complete write operation, including its validation reads."""
        with self._lock:
            if self.conn.in_transaction:
                raise RuntimeError("Use the transaction handle inside a transaction")
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield Transaction(self.conn)
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise

    def q(self, sql: str, params: tuple = ()):
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def q1(self, sql: str, params: tuple = ()):
        rows = self.q(sql, params)
        return rows[0] if rows else None
