import sqlite3

from fastapi.testclient import TestClient

from workbench import backup
from workbench.api import create_app
from workbench.db import Database, SCHEMA_VERSION
from workbench.engine.mock import MockWritingEngine
from workbench.service import Service, normalize_idea_topic


def setup_client(path=":memory:"):
    db = Database(path)
    service = Service(db, MockWritingEngine())
    return db, TestClient(create_app(service))


def save(client, topic="为什么失败会改变过去努力的意义", **extra):
    response = client.post("/ideas", json={"topic": topic, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_normalized_topic_dedup_is_narrow_and_deterministic():
    _, client = setup_client()
    first = save(client, "  ＡI\n写作  ", note="第一条")
    duplicate = save(client, "ai 写作", origin="generated", hook="另一说明")
    distinct = save(client, "AI 写作真的有用吗？")
    assert normalize_idea_topic("  ＡI\n写作  ") == "ai 写作"
    assert first["created"] is True and duplicate["created"] is False
    assert duplicate["idea"]["id"] == first["idea"]["id"]
    assert distinct["created"] is True
    assert len(client.get("/ideas").json()["ideas"]) == 2


def test_create_limits_and_origin_validation():
    _, client = setup_client()
    assert client.post("/ideas", json={"topic": " "}).status_code == 400
    assert client.post("/ideas", json={"topic": "字" * 501}).status_code == 400
    assert client.post("/ideas", json={"topic": "有效", "note": "字" * 2001}).status_code == 400
    assert client.post("/ideas", json={"topic": "有效", "origin": "legacy"}).status_code == 400
    result = save(client, "有效", origin="generated", hook="说明", domain="work")
    assert result["idea"]["origin"] == "generated"


def test_list_search_status_counts_and_literal_wildcards():
    _, client = setup_client()
    one = save(client, "职业转换", note="关于教师", domain_name="职场")["idea"]
    two = save(client, "为什么 100% 努力仍会失败")["idea"]
    client.patch(f"/ideas/{one['id']}", json={"status": "archived"})
    archived = client.get("/ideas", params={"status": "archived", "q": "教师"}).json()
    assert [item["id"] for item in archived["ideas"]] == [one["id"]]
    assert archived["counts"] == {"to_write": 1, "written": 0, "archived": 1}
    literal = client.get("/ideas", params={"q": "100%"}).json()["ideas"]
    assert [item["id"] for item in literal] == [two["id"]]
    assert client.get("/ideas", params={"status": "unknown"}).status_code == 400
    assert client.get("/ideas", params={"limit": 201}).status_code == 400


def test_update_note_and_status_without_rewriting_topic():
    _, client = setup_client()
    idea = save(client, "边界问题")["idea"]
    updated = client.patch(f"/ideas/{idea['id']}",
                           json={"note": "从具体事件切入", "status": "archived"})
    assert updated.status_code == 200
    assert updated.json()["note"] == "从具体事件切入"
    assert updated.json()["topic"] == "边界问题"
    assert client.patch(f"/ideas/{idea['id']}", json={"status": "written"}).status_code == 409
    assert client.patch(f"/ideas/{idea['id']}", json={"topic": "偷改"}).status_code == 400
    assert client.patch("/ideas/missing", json={"note": "x"}).status_code == 404


def test_legacy_import_is_atomic_counted_and_idempotent():
    _, client = setup_client()
    items = [
        {"text": "旧话题一", "hook": "说明一", "domain": "life", "domainName": "生活"},
        {"text": "旧话题二", "hook": "说明二", "domain": "work", "domainName": "职场"},
        {"text": " 旧话题一 ", "hook": "重复"},
    ]
    first = client.post("/ideas/import-legacy", json={"items": items})
    assert first.status_code == 200
    assert first.json() == {"received": 3, "imported": 2, "existing": 1}
    second = client.post("/ideas/import-legacy", json={"items": items})
    assert second.json() == {"received": 3, "imported": 0, "existing": 3}
    assert {item["origin"] for item in client.get("/ideas").json()["ideas"]} == {"legacy"}


def test_invalid_legacy_batch_does_not_partially_import():
    db, client = setup_client()
    response = client.post("/ideas/import-legacy", json={"items": [
        {"text": "有效旧题"}, {"text": "字" * 501},
    ]})
    assert response.status_code == 400
    assert db.q("SELECT * FROM ideas") == []
    assert client.post("/ideas/import-legacy", json={"items": [{}] * 201}).status_code == 400


def test_quick_write_task_links_idea_in_same_transaction():
    db, client = setup_client()
    idea = save(client, "等待为何改变一个人")["idea"]
    response = client.post("/tasks", json={
        "input_mode": "topic_only", "topic": " 等待为何改变一个人 ",
        "idea_id": idea["id"], "writing_mode": "deep_narrative",
    })
    assert response.status_code == 200, response.text
    linked = db.q1("SELECT * FROM ideas WHERE id=?", (idea["id"],))
    assert linked["task_id"] == response.json()["id"] and linked["status"] == "written"
    assert client.post("/tasks", json={
        "input_mode": "topic_only", "topic": idea["topic"], "idea_id": idea["id"],
    }).status_code == 409
    assert client.patch(f"/ideas/{idea['id']}", json={"status": "to_write"}).status_code == 409


def test_bad_idea_link_creates_no_task_and_keeps_idea_unlinked():
    db, client = setup_client()
    idea = save(client, "原话题")["idea"]
    before = len(db.q("SELECT * FROM tasks"))
    mismatch = client.post("/tasks", json={
        "input_mode": "topic_only", "topic": "另一个话题", "idea_id": idea["id"],
    })
    assert mismatch.status_code == 409
    assert len(db.q("SELECT * FROM tasks")) == before
    assert db.q1("SELECT task_id,status FROM ideas WHERE id=?", (idea["id"],)) == {
        "task_id": None, "status": "to_write"}
    wrong_mode = client.post("/tasks", json={
        "input_mode": "source_grounded", "type": "essay", "material": "素材",
        "idea_id": idea["id"],
    })
    assert wrong_mode.status_code == 400
    assert len(db.q("SELECT * FROM tasks")) == before


def test_v6_database_and_backup_contract_upgrade_to_v7(tmp_path):
    path = tmp_path / "v6.sqlite3"
    db = Database(path)
    db.conn.close()
    with sqlite3.connect(path) as conn:
        conn.execute("DROP INDEX ideas_task")
        conn.execute("DROP INDEX ideas_status_updated")
        conn.execute("DROP TABLE ideas")
        conn.execute("PRAGMA user_version=6")
    counts = backup._inspect_sqlite(path)
    assert "ideas" not in counts
    upgraded = Database(path)
    assert upgraded.q1("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    assert upgraded.q1("SELECT name FROM sqlite_master WHERE name='ideas'")


def test_v7_backup_contains_ideas_and_rejects_bad_task_relation():
    db, client = setup_client()
    idea = save(client, "备份里的选题")["idea"]
    task = client.post("/tasks", json={
        "input_mode": "topic_only", "topic": idea["topic"], "idea_id": idea["id"],
    }).json()
    inspected = backup.inspect_backup(backup.create_backup(db).content)
    assert inspected.summary["table_counts"]["ideas"] == 1
    unlinked = save(client, "错误的已写状态")["idea"]
    db.exec("UPDATE ideas SET status='written' WHERE id=?", (unlinked["id"],))
    try:
        backup.create_backup(db)
        assert False, "written idea must point to a task"
    except backup.BackupError as exc:
        assert "ideas.status_task" in str(exc)
    db.exec("UPDATE ideas SET status='to_write' WHERE id=?", (unlinked["id"],))
    other = client.post("/tasks", json={
        "input_mode": "source_grounded", "type": "essay", "material": "材料",
    }).json()
    db.exec("UPDATE ideas SET task_id=? WHERE id=?", (other["id"], idea["id"]))
    try:
        backup.create_backup(db)
        assert False, "idea must only point to a topic-only task"
    except backup.BackupError as exc:
        assert "ideas.task" in str(exc)
    assert task["id"] != other["id"]
