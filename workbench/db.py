"""SQLite persistence for the Workbench (product/06_DATA_MODEL.md)."""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
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
  meaning_id TEXT);
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
"""

_lock = threading.Lock()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Database:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or os.environ.get("WORKBENCH_DB", DEFAULT_DB))
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        with _lock:
            self.conn.executescript(SCHEMA)
            self._migrate()
            self.conn.commit()

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

    # -- tiny helpers ----------------------------------------------------

    def exec(self, sql: str, params: tuple = ()):
        with _lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def q(self, sql: str, params: tuple = ()):
        with _lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def q1(self, sql: str, params: tuple = ()):
        rows = self.q(sql, params)
        return rows[0] if rows else None
