"""Create, inspect, and restore self-contained local workspace backups."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import uuid
from urllib.parse import quote
import zipfile

from .db import Database, SCHEMA_VERSION


PACKAGE_FORMAT = "narrative-writing-workbench-backup"
FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
SNAPSHOT_NAME = "workspace.sqlite3"
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024

REQUIRED_COLUMNS = {
    "projects": {"id", "name", "description", "created_at", "updated_at"},
    "sources": {"id", "project_id", "title", "type", "content", "metadata_json", "created_at", "updated_at"},
    "tasks": {"id", "project_id", "type", "title", "instruction", "status", "expected_language", "created_at", "updated_at", "input_mode", "topic", "writing_mode", "angle_mode", "custom_angle"},
    "task_sources": {"task_id", "source_id", "role"},
    "writing_configs": {"task_id", "immersion", "explicitness", "intensity", "target_length", "locks_json", "constraints_json"},
    "engine_plans": {"id", "task_id", "schema_version", "data_json", "created_at", "meaning_id", "inputs_json", "operation_id"},
    "meaning_discoveries": {"id", "task_id", "topic", "selected_angle_id", "status", "data_json", "created_at", "operation_id", "inputs_json"},
    "drafts": {"id", "task_id", "current_version_id", "working_content", "updated_at", "revision"},
    "versions": {"id", "draft_id", "parent_version_id", "content", "source_type", "instruction", "created_at", "engine_plan_id", "restore_source_version_id"},
    "proposed_patches": {"id", "draft_id", "base_version_id", "selection_json", "instruction", "before_text", "after_text", "status", "locks_json", "error", "created_at", "base_revision", "accepted_version_id", "task_locks_json"},
    "reviews": {"id", "draft_id", "version_id", "summary_json", "issues_json", "created_at", "content_hash", "draft_revision", "config_json", "operation_id"},
    "writing_operations": {"id", "task_id", "kind", "process_id", "status", "stage", "started_at", "finished_at", "elapsed_ms", "input_fingerprint", "snapshot_json", "retry_of", "error_code", "result_json", "usage_json"},
    "operation_events": {"operation_id", "seq", "kind", "data_json", "elapsed_ms", "created_at"},
    "operation_records": {"id", "operation_id", "category", "name", "status", "data_json", "elapsed_ms", "created_at"},
    "generation_results": {"id", "task_id", "engine_plan_id", "content", "accepted_version_id", "created_at", "operation_id"},
}
REQUIRED_INDEX_SQL = {
    "one_running_operation": "create unique index one_running_operation on writing_operations(task_id) where status='running'",
    "operation_records_operation": "create index operation_records_operation on operation_records(operation_id)",
    "versions_plan": "create index versions_plan on versions(engine_plan_id)",
}


class BackupError(ValueError):
    """The package cannot safely be used as a Workbench backup."""


@dataclass(frozen=True)
class BackupArtifact:
    content: bytes
    filename: str

    @property
    def media_type(self):
        return "application/zip"

    @property
    def headers(self):
        encoded = quote(self.filename, safe="")
        return {
            "Content-Disposition": (
                f'attachment; filename="workbench-backup.nwb-backup.zip"; '
                f"filename*=UTF-8''{encoded}"
            ),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        }


@dataclass(frozen=True)
class InspectedBackup:
    manifest: dict
    snapshot: bytes

    @property
    def summary(self):
        return {
            "valid": True,
            "format_version": self.manifest["format_version"],
            "created_at": self.manifest["created_at"],
            "schema_version": self.manifest["schema_version"],
            "snapshot_bytes": self.manifest["snapshot"]["bytes"],
            "snapshot_sha256": self.manifest["snapshot"]["sha256"],
            "table_counts": self.manifest["table_counts"],
        }


def _utc_stamp() -> tuple[str, str]:
    value = datetime.now(timezone.utc)
    return value.isoformat(timespec="seconds"), value.strftime("%Y%m%d-%H%M%S")


def _hash(data: bytes) -> str:
    return sha256(data).hexdigest()


def _read_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {table: conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            for table in sorted(REQUIRED_COLUMNS)}


def _validate_manifest(raw: bytes) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError("manifest.json is not valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise BackupError("manifest.json must contain an object.")
    if (value.get("format") != PACKAGE_FORMAT
            or type(value.get("format_version")) is not int
            or value["format_version"] != FORMAT_VERSION):
        raise BackupError("This backup package format is not supported.")
    if type(value.get("schema_version")) is not int or value["schema_version"] != SCHEMA_VERSION:
        if type(value.get("schema_version")) is int and value["schema_version"] > SCHEMA_VERSION:
            raise BackupError("This backup was created by a newer Workbench schema.")
        raise BackupError("This backup schema is not supported.")
    if not isinstance(value.get("created_at"), str) or not value["created_at"]:
        raise BackupError("The backup creation time is missing.")
    try:
        created = datetime.fromisoformat(value["created_at"])
        if created.utcoffset() != timezone.utc.utcoffset(created):
            raise ValueError
    except ValueError as exc:
        raise BackupError("The backup creation time must be a UTC ISO 8601 value.") from exc
    snapshot = value.get("snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("filename") != SNAPSHOT_NAME:
        raise BackupError("The snapshot manifest entry is invalid.")
    size, digest = snapshot.get("bytes"), snapshot.get("sha256")
    if type(size) is not int or not 0 < size <= MAX_SNAPSHOT_BYTES:
        raise BackupError("The declared snapshot size is invalid or too large.")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise BackupError("The snapshot SHA-256 is invalid.")
    counts = value.get("table_counts")
    if not isinstance(counts, dict) or set(counts) != set(REQUIRED_COLUMNS):
        raise BackupError("The table count manifest is incomplete.")
    if any(type(n) is not int or n < 0 for n in counts.values()):
        raise BackupError("The table count manifest is invalid.")
    return value


def _orphan_checks() -> list[tuple[str, str]]:
    """Named queries which must all return zero rows."""
    return [
        ("sources.project", "SELECT 1 FROM sources s LEFT JOIN projects p ON p.id=s.project_id WHERE s.project_id IS NOT NULL AND p.id IS NULL LIMIT 1"),
        ("tasks.project", "SELECT 1 FROM tasks t LEFT JOIN projects p ON p.id=t.project_id WHERE t.project_id IS NOT NULL AND p.id IS NULL LIMIT 1"),
        ("task_sources.task", "SELECT 1 FROM task_sources x LEFT JOIN tasks t ON t.id=x.task_id WHERE t.id IS NULL LIMIT 1"),
        ("task_sources.source", "SELECT 1 FROM task_sources x LEFT JOIN sources s ON s.id=x.source_id WHERE s.id IS NULL LIMIT 1"),
        ("writing_configs.task", "SELECT 1 FROM writing_configs x LEFT JOIN tasks t ON t.id=x.task_id WHERE t.id IS NULL LIMIT 1"),
        ("engine_plans.task", "SELECT 1 FROM engine_plans x LEFT JOIN tasks t ON t.id=x.task_id WHERE t.id IS NULL LIMIT 1"),
        ("engine_plans.meaning", "SELECT 1 FROM engine_plans x LEFT JOIN meaning_discoveries m ON m.id=x.meaning_id WHERE x.meaning_id IS NOT NULL AND (m.id IS NULL OR m.task_id<>x.task_id) LIMIT 1"),
        ("engine_plans.operation", "SELECT 1 FROM engine_plans x LEFT JOIN writing_operations o ON o.id=x.operation_id WHERE x.operation_id IS NOT NULL AND (o.id IS NULL OR o.task_id<>x.task_id) LIMIT 1"),
        ("meaning.task", "SELECT 1 FROM meaning_discoveries x LEFT JOIN tasks t ON t.id=x.task_id WHERE t.id IS NULL LIMIT 1"),
        ("meaning.operation", "SELECT 1 FROM meaning_discoveries x LEFT JOIN writing_operations o ON o.id=x.operation_id WHERE x.operation_id IS NOT NULL AND (o.id IS NULL OR o.task_id<>x.task_id) LIMIT 1"),
        ("drafts.task", "SELECT 1 FROM drafts x LEFT JOIN tasks t ON t.id=x.task_id WHERE t.id IS NULL LIMIT 1"),
        ("drafts.unique_task", "SELECT 1 FROM drafts GROUP BY task_id HAVING count(*)>1 LIMIT 1"),
        ("drafts.current_version", "SELECT 1 FROM drafts d LEFT JOIN versions v ON v.id=d.current_version_id WHERE d.current_version_id IS NOT NULL AND (v.id IS NULL OR v.draft_id<>d.id) LIMIT 1"),
        ("versions.draft", "SELECT 1 FROM versions v LEFT JOIN drafts d ON d.id=v.draft_id WHERE d.id IS NULL LIMIT 1"),
        ("versions.parent", "SELECT 1 FROM versions v LEFT JOIN versions p ON p.id=v.parent_version_id WHERE v.parent_version_id IS NOT NULL AND (p.id IS NULL OR p.draft_id<>v.draft_id) LIMIT 1"),
        ("versions.restore_source", "SELECT 1 FROM versions v LEFT JOIN versions p ON p.id=v.restore_source_version_id WHERE v.restore_source_version_id IS NOT NULL AND (p.id IS NULL OR p.draft_id<>v.draft_id) LIMIT 1"),
        ("versions.plan", "SELECT 1 FROM versions v JOIN drafts d ON d.id=v.draft_id LEFT JOIN engine_plans p ON p.id=v.engine_plan_id WHERE v.engine_plan_id IS NOT NULL AND (p.id IS NULL OR p.task_id<>d.task_id) LIMIT 1"),
        ("patches.draft", "SELECT 1 FROM proposed_patches x LEFT JOIN drafts d ON d.id=x.draft_id WHERE d.id IS NULL LIMIT 1"),
        ("patches.versions", "SELECT 1 FROM proposed_patches x LEFT JOIN versions b ON b.id=x.base_version_id LEFT JOIN versions a ON a.id=x.accepted_version_id WHERE b.id IS NULL OR b.draft_id<>x.draft_id OR (x.accepted_version_id IS NOT NULL AND (a.id IS NULL OR a.draft_id<>x.draft_id)) LIMIT 1"),
        ("reviews.draft_version", "SELECT 1 FROM reviews x LEFT JOIN drafts d ON d.id=x.draft_id LEFT JOIN versions v ON v.id=x.version_id WHERE d.id IS NULL OR v.id IS NULL OR v.draft_id<>x.draft_id LIMIT 1"),
        ("reviews.operation", "SELECT 1 FROM reviews x JOIN drafts d ON d.id=x.draft_id LEFT JOIN writing_operations o ON o.id=x.operation_id WHERE x.operation_id IS NOT NULL AND (o.id IS NULL OR o.task_id<>d.task_id) LIMIT 1"),
        ("operations.task", "SELECT 1 FROM writing_operations x LEFT JOIN tasks t ON t.id=x.task_id WHERE t.id IS NULL LIMIT 1"),
        ("operations.retry", "SELECT 1 FROM writing_operations x LEFT JOIN writing_operations p ON p.id=x.retry_of WHERE x.retry_of IS NOT NULL AND (p.id IS NULL OR p.task_id<>x.task_id) LIMIT 1"),
        ("events.operation", "SELECT 1 FROM operation_events x LEFT JOIN writing_operations o ON o.id=x.operation_id WHERE o.id IS NULL LIMIT 1"),
        ("records.operation", "SELECT 1 FROM operation_records x LEFT JOIN writing_operations o ON o.id=x.operation_id WHERE o.id IS NULL LIMIT 1"),
        ("results.task", "SELECT 1 FROM generation_results x LEFT JOIN tasks t ON t.id=x.task_id WHERE t.id IS NULL LIMIT 1"),
        ("results.plan", "SELECT 1 FROM generation_results x LEFT JOIN engine_plans p ON p.id=x.engine_plan_id WHERE x.engine_plan_id IS NOT NULL AND (p.id IS NULL OR p.task_id<>x.task_id) LIMIT 1"),
        ("results.operation", "SELECT 1 FROM generation_results x LEFT JOIN writing_operations o ON o.id=x.operation_id WHERE x.operation_id IS NOT NULL AND (o.id IS NULL OR o.task_id<>x.task_id) LIMIT 1"),
        ("results.accepted_version", "SELECT 1 FROM generation_results x LEFT JOIN versions v ON v.id=x.accepted_version_id LEFT JOIN drafts d ON d.id=v.draft_id WHERE x.accepted_version_id IS NOT NULL AND (v.id IS NULL OR d.task_id<>x.task_id) LIMIT 1"),
    ]


def _inspect_sqlite(path: Path, expected_counts: dict | None = None) -> dict[str, int]:
    try:
        uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA trusted_schema=OFF")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BackupError("The SQLite snapshot failed its integrity check.")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise BackupError("This backup was created by a newer Workbench schema.")
        if version != SCHEMA_VERSION:
            raise BackupError("This backup schema is not supported.")
        objects = conn.execute(
            "SELECT type,name FROM sqlite_master WHERE type IN ('table','view','trigger')"
        ).fetchall()
        tables = {name for type_, name in objects if type_ == "table" and not name.startswith("sqlite_")}
        if tables != set(REQUIRED_COLUMNS):
            raise BackupError("The SQLite snapshot has an unexpected table set.")
        if any(type_ in ("view", "trigger") for type_, _ in objects):
            raise BackupError("The SQLite snapshot contains unsupported schema objects.")
        for table, required in REQUIRED_COLUMNS.items():
            columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
            if columns != required:
                raise BackupError(f"The {table} table schema is incompatible.")
        indexes = conn.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        ).fetchall()
        index_sql = {name: " ".join(sql.lower().split()) for name, sql in indexes}
        if index_sql != REQUIRED_INDEX_SQL:
            raise BackupError("The SQLite snapshot has an incompatible index schema.")
        counts = _read_counts(conn)
        if expected_counts is not None and counts != expected_counts:
            raise BackupError("The snapshot table counts do not match the manifest.")
        for name, query in _orphan_checks():
            if conn.execute(query).fetchone():
                raise BackupError(f"The snapshot has an invalid reference ({name}).")
        return counts
    except BackupError:
        raise
    except sqlite3.Error as exc:
        raise BackupError("The SQLite snapshot cannot be read safely.") from exc
    finally:
        if "conn" in locals():
            conn.close()


def create_backup(db: Database) -> BackupArtifact:
    created_at, file_stamp = _utc_stamp()
    with tempfile.TemporaryDirectory(prefix="nwb-backup-") as temp:
        snapshot_path = Path(temp) / SNAPSHOT_NAME
        db.backup_to(snapshot_path)
        snapshot = snapshot_path.read_bytes()
        if not snapshot or len(snapshot) > MAX_SNAPSHOT_BYTES:
            raise BackupError("The workspace snapshot is empty or too large to back up.")
        counts = _inspect_sqlite(snapshot_path)
    manifest = {
        "format": PACKAGE_FORMAT,
        "format_version": FORMAT_VERSION,
        "created_at": created_at,
        "schema_version": SCHEMA_VERSION,
        "snapshot": {"filename": SNAPSHOT_NAME, "bytes": len(snapshot), "sha256": _hash(snapshot)},
        "table_counts": counts,
    }
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(MANIFEST_NAME, manifest_bytes)
        archive.writestr(SNAPSHOT_NAME, snapshot)
    content = output.getvalue()
    if len(content) > MAX_ARCHIVE_BYTES:
        raise BackupError("The compressed backup is too large to download safely.")
    return BackupArtifact(content, f"workbench-{file_stamp}.nwb-backup.zip")


def inspect_backup(content: bytes) -> InspectedBackup:
    if not isinstance(content, bytes) or not content:
        raise BackupError("The backup file is empty.")
    if len(content) > MAX_ARCHIVE_BYTES:
        raise BackupError("The backup file is too large.")
    try:
        with zipfile.ZipFile(BytesIO(content), "r") as archive:
            entries = archive.infolist()
            if len(entries) != 2 or {entry.filename for entry in entries} != {MANIFEST_NAME, SNAPSHOT_NAME}:
                raise BackupError("A backup must contain exactly manifest.json and workspace.sqlite3.")
            by_name = {entry.filename: entry for entry in entries}
            manifest_info, snapshot_info = by_name[MANIFEST_NAME], by_name[SNAPSHOT_NAME]
            if any(entry.is_dir() or entry.flag_bits & 1 or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                   for entry in entries):
                raise BackupError("The backup contains an unsupported ZIP entry.")
            if manifest_info.file_size > MAX_MANIFEST_BYTES or snapshot_info.file_size > MAX_SNAPSHOT_BYTES:
                raise BackupError("The backup expands beyond the allowed size.")
            manifest_raw = archive.read(manifest_info)
            snapshot = archive.read(snapshot_info)
    except BackupError:
        raise
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise BackupError("The backup is not a readable ZIP package.") from exc
    manifest = _validate_manifest(manifest_raw)
    declared = manifest["snapshot"]
    if len(snapshot) != declared["bytes"] or _hash(snapshot) != declared["sha256"]:
        raise BackupError("The SQLite snapshot size or SHA-256 does not match the manifest.")
    with tempfile.TemporaryDirectory(prefix="nwb-inspect-") as temp:
        snapshot_path = Path(temp) / SNAPSHOT_NAME
        snapshot_path.write_bytes(snapshot)
        _inspect_sqlite(snapshot_path, manifest["table_counts"])
    return InspectedBackup(manifest, snapshot)


def restore_backup(content: bytes, restore_root: str | Path) -> dict:
    inspected = inspect_backup(content)
    root = Path(restore_root)
    root.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:8]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    final_dir = root / f"restored-{stamp}-{token}"
    temp_dir = root / f".restore-{uuid.uuid4().hex}"
    try:
        temp_dir.mkdir()
        target = temp_dir / "workbench.db"
        with target.open("xb") as handle:
            handle.write(inspected.snapshot)
            handle.flush()
            os.fsync(handle.fileno())
        _inspect_sqlite(target, inspected.manifest["table_counts"])
        os.rename(temp_dir, final_dir)
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return {
        **inspected.summary,
        "restored_directory": str(final_dir.resolve()),
        "database_path": str((final_dir / "workbench.db").resolve()),
    }
