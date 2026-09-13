from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient

from workbench import backup
from workbench.api import create_app
from workbench.backup import BackupError, create_backup, inspect_backup, restore_backup
from workbench.db import Database
from workbench.engine.mock import MockWritingEngine
from workbench.service import Service


def populated_service(db, restore_root=None):
    svc = Service(db, MockWritingEngine(), restore_root=restore_root)
    task = svc.create_task({
        "input_mode": "source_grounded", "type": "essay",
        "title": "备份演练", "material": "素材与细节",
        "instruction": "写出情绪的推进",
    })
    generated = svc.generate(task["id"])
    saved = svc.autosave(
        generated["draft_id"], "最新工作副本\n\n保留空行🙂", generated["revision"])
    svc.checkpoint(task["id"], saved["revision"])
    return svc, task["id"]


def unpack(content):
    with zipfile.ZipFile(BytesIO(content)) as archive:
        return (json.loads(archive.read("manifest.json")),
                archive.read("workspace.sqlite3"))


def repack(manifest, snapshot, extra=None):
    manifest = dict(manifest)
    manifest["snapshot"] = dict(manifest["snapshot"])
    manifest["snapshot"].update(
        bytes=len(snapshot), sha256=sha256(snapshot).hexdigest())
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("workspace.sqlite3", snapshot)
        if extra:
            archive.writestr(extra, b"unexpected")
    return output.getvalue()


def mutate_snapshot(snapshot, tmp_path, sql):
    path = tmp_path / "mutated.sqlite3"
    path.write_bytes(snapshot)
    with sqlite3.connect(path) as conn:
        conn.execute(sql)
    return path.read_bytes()


def test_wal_backup_is_consistent_complete_and_private(tmp_path):
    db_path = tmp_path / "live.db"
    db = Database(db_path)
    db.conn.execute("PRAGMA journal_mode=WAL")
    db.conn.execute("PRAGMA wal_autocheckpoint=0")
    svc, _ = populated_service(db)
    (tmp_path / "settings.json").write_text(
        '{"api_key":"sk-private-never-export"}', encoding="utf-8")

    artifact = create_backup(db)
    inspected = inspect_backup(artifact.content)
    manifest, snapshot = unpack(artifact.content)

    assert set(zipfile.ZipFile(BytesIO(artifact.content)).namelist()) == {
        "manifest.json", "workspace.sqlite3"}
    assert manifest == inspected.manifest
    assert manifest["snapshot"]["bytes"] == len(snapshot)
    assert manifest["snapshot"]["sha256"] == sha256(snapshot).hexdigest()
    assert manifest["table_counts"]["tasks"] == 1
    assert manifest["table_counts"]["versions"] == 2
    assert b"sk-private-never-export" not in artifact.content
    assert b"settings.json" not in artifact.content
    assert svc.db.q1("SELECT working_content FROM drafts")["working_content"].endswith("🙂")


@pytest.mark.parametrize(
    "kind", ["hash", "missing", "extra", "sqlite", "future", "orphan"])
def test_inspection_rejects_tampering_and_incompatible_packages(tmp_path, kind):
    svc, _ = populated_service(Database(":memory:"))
    manifest, snapshot = unpack(create_backup(svc.db).content)
    if kind == "hash":
        manifest["snapshot"]["sha256"] = "0" * 64
        content = repack(manifest, snapshot)
        # repack repairs the hash; change it after that.
        with zipfile.ZipFile(BytesIO(content)) as archive:
            repaired = json.loads(archive.read("manifest.json"))
        repaired["snapshot"]["sha256"] = "0" * 64
        output = BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(repaired))
            archive.writestr("workspace.sqlite3", snapshot)
        content = output.getvalue()
    elif kind == "missing":
        output = BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
        content = output.getvalue()
    elif kind == "extra":
        content = repack(manifest, snapshot, "../settings.json")
    elif kind == "sqlite":
        content = repack(manifest, b"not a SQLite database")
    elif kind == "future":
        changed = mutate_snapshot(snapshot, tmp_path, "PRAGMA user_version=99")
        manifest["schema_version"] = 99
        content = repack(manifest, changed)
    else:
        changed = mutate_snapshot(
            snapshot, tmp_path,
            "UPDATE task_sources SET source_id='missing-source'")
        content = repack(manifest, changed)

    with pytest.raises(BackupError):
        inspect_backup(content)


def test_limits_and_broken_zip_are_rejected(monkeypatch):
    with pytest.raises(BackupError):
        inspect_backup(b"not a zip")
    monkeypatch.setattr(backup, "MAX_ARCHIVE_BYTES", 3)
    with pytest.raises(BackupError, match="too large"):
        inspect_backup(b"four")


def test_restore_creates_independent_workspace_and_cleans_failure(tmp_path, monkeypatch):
    current = Database(tmp_path / "current.db")
    svc, tid = populated_service(current)
    artifact = create_backup(current)
    before = svc.task_detail(tid)["draft"].copy()

    first = restore_backup(artifact.content, tmp_path / "restored")
    second = restore_backup(artifact.content, tmp_path / "restored")
    assert first["database_path"] != second["database_path"]
    restored = Database(first["database_path"])
    assert restored.q1("SELECT working_content FROM drafts")["working_content"] == before["working_content"]
    assert len(restored.q("SELECT * FROM versions")) == 2
    assert svc.task_detail(tid)["draft"] == before

    real_rename = backup.os.rename
    monkeypatch.setattr(backup.os, "rename", lambda *_: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        restore_backup(artifact.content, tmp_path / "failed")
    assert not list((tmp_path / "failed").iterdir())
    monkeypatch.setattr(backup.os, "rename", real_rename)


def test_backup_api_round_trip_and_request_size_gate(tmp_path):
    svc, tid = populated_service(Database(":memory:"), tmp_path / "restored")
    client = TestClient(create_app(svc))
    before = svc.task_detail(tid)["draft"].copy()

    exported = client.get("/backups/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/zip")
    assert exported.headers["cache-control"] == "no-store"
    assert ".nwb-backup.zip" in exported.headers["content-disposition"]

    inspected = client.post(
        "/backups/inspect", content=exported.content,
        headers={"Content-Type": "application/zip"})
    assert inspected.status_code == 200
    assert inspected.json()["table_counts"]["tasks"] == 1

    restored = client.post(
        "/backups/restore", content=exported.content,
        headers={"Content-Type": "application/zip"})
    assert restored.status_code == 200
    path = Path(restored.json()["database_path"])
    assert path.is_file() and path.parent.parent == tmp_path / "restored"
    assert svc.task_detail(tid)["draft"] == before

    too_large = client.post(
        "/backups/inspect", content=b"x",
        headers={"Content-Length": str(backup.MAX_ARCHIVE_BYTES + 1)})
    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "BACKUP_TOO_LARGE"
