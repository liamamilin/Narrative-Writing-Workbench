from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from workbench import backup
from workbench.api import create_app
from workbench.db import Database, SCHEMA_VERSION
from workbench.engine.mock import MockWritingEngine
from workbench.service import Service


def setup_article(content="第一段。<script>private()</script>\n\n第二段继续展开。"):
    db = Database(":memory:")
    service = Service(db, MockWritingEngine())
    client = TestClient(create_app(service))
    task = client.post("/tasks", json={
        "input_mode": "draft_revision", "type": "essay",
        "title": "欲买桂花同载酒", "material": content,
    }).json()
    detail = client.get(f"/tasks/{task['id']}").json()
    return db, service, client, task["id"], detail["draft"]


def create_share(client, tid, revision, **extra):
    payload = {"expected_revision": revision, "author": "林墨", **extra}
    response = client.post(f"/tasks/{tid}/share", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["share"]


def test_share_snapshot_public_contract_and_article_rendering():
    db, _, client, tid, draft = setup_article()
    missing_revision = client.post(f"/tasks/{tid}/share", json={})
    assert missing_revision.status_code == 400
    assert missing_revision.json()["error"]["code"] == "VALIDATION"

    share = create_share(client, tid, draft["revision"])
    assert share["path"].startswith("/s/")
    assert len(share["token"]) >= 32
    assert share["excerpt"].startswith("第一段")
    assert db.q1("SELECT content FROM article_shares WHERE id=?", (share["id"],))["content"] == draft["working_content"]

    meta = client.get(f"{share['path']}/meta")
    assert meta.status_code == 200
    assert set(meta.json()) == {
        "title", "content", "author", "excerpt", "created_at", "reading_minutes",
    }
    serialized = meta.text
    for private_name in ("task_id", "draft_id", "draft_revision", "instruction", "model", "api_key"):
        assert private_name not in serialized
    assert meta.headers["x-robots-tag"] == "noindex, nofollow"
    assert meta.headers["referrer-policy"] == "no-referrer"

    page = client.get(share["path"])
    assert page.status_code == 200
    assert "欲买桂花同载酒" in page.text
    assert "&lt;script&gt;private()&lt;/script&gt;" in page.text
    assert "<script>private()</script>" not in page.text
    assert "这是作者发布时的版本快照" in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]


def test_share_is_immutable_then_replace_revokes_old_link():
    _, service, client, tid, draft = setup_article("旧稿第一段。\n\n旧稿第二段。")
    old = create_share(client, tid, draft["revision"], excerpt="旧摘要")
    saved = service.autosave(draft["id"], "新稿已经修改。", draft["revision"])

    assert client.get(old["path"]).status_code == 200
    assert "旧稿第一段" in client.get(old["path"]).text
    assert "新稿已经修改" not in client.get(old["path"]).text
    current = client.get(f"/tasks/{tid}/share").json()["share"]
    assert current["stale"] is True

    conflict = client.post(f"/tasks/{tid}/share", json={
        "expected_revision": saved["revision"], "author": "林墨",
    })
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "SHARE_EXISTS"
    new = create_share(
        client, tid, saved["revision"], replace=True, excerpt="新摘要")
    assert new["token"] != old["token"] and new["stale"] is False
    assert client.get(old["path"]).status_code == 404
    assert "新稿已经修改" in client.get(new["path"]).text


def test_revoke_and_task_delete_make_public_link_unavailable():
    db, _, client, tid, draft = setup_article()
    share = create_share(client, tid, draft["revision"])
    revoked = client.delete(f"/tasks/{tid}/share")
    assert revoked.json()["revoked"] is True
    assert client.get(share["path"]).status_code == 404

    replacement = create_share(client, tid, draft["revision"])
    assert client.delete(f"/tasks/{tid}").status_code == 200
    assert client.get(replacement["path"]).status_code == 404
    assert db.q("SELECT * FROM article_shares WHERE task_id=?", (tid,)) == []


def test_share_validation_and_stale_revision():
    _, service, client, tid, draft = setup_article()
    assert client.post(f"/tasks/{tid}/share", json={
        "expected_revision": draft["revision"], "author": "字" * 81,
    }).status_code == 400
    saved = service.autosave(draft["id"], "另一标签页的内容", draft["revision"])
    stale = client.post(f"/tasks/{tid}/share", json={
        "expected_revision": draft["revision"],
    })
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_BASE"
    assert create_share(client, tid, saved["revision"])["draft_revision"] == saved["revision"]


def test_v7_database_upgrades_and_v8_backup_validates_share_relations(tmp_path):
    path = tmp_path / "v7.sqlite3"
    db = Database(path)
    db.conn.close()
    with sqlite3.connect(path) as conn:
        conn.execute("DROP INDEX active_article_share")
        conn.execute("DROP INDEX article_shares_task")
        conn.execute("DROP TABLE article_shares")
        conn.execute("PRAGMA user_version=7")
    counts = backup._inspect_sqlite(path)
    assert "article_shares" not in counts
    upgraded = Database(path)
    assert upgraded.q1("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    assert upgraded.q1("SELECT name FROM sqlite_master WHERE name='article_shares'")
    upgraded.conn.close()

    db, _, client, tid, draft = setup_article()
    create_share(client, tid, draft["revision"])
    inspected = backup.inspect_backup(backup.create_backup(db).content)
    assert inspected.summary["table_counts"]["article_shares"] == 1
    other = client.post("/tasks", json={
        "input_mode": "draft_revision", "type": "essay", "material": "另一稿",
    }).json()["id"]
    other_draft = client.get(f"/tasks/{other}").json()["draft"]
    db.exec("UPDATE article_shares SET draft_id=? WHERE task_id=?", (other_draft["id"], tid))
    try:
        backup.create_backup(db)
        assert False, "share draft must belong to the same task"
    except backup.BackupError as exc:
        assert "article_shares.task_draft" in str(exc)
