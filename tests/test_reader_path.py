import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from workbench import backup
from workbench.api import create_app
from workbench.db import Database, SCHEMA_VERSION
from workbench.engine.mock import MockWritingEngine
from workbench.service import Service


def setup_reader(content, engine=None):
    db = Database(":memory:")
    svc = Service(db, engine or MockWritingEngine())
    client = TestClient(create_app(svc))
    response = client.post("/tasks", json={
        "input_mode": "draft_revision", "type": "essay",
        "title": "路径测试", "instruction": "收紧实际推进。", "material": content,
    })
    assert response.status_code == 200, response.text
    tid = response.json()["id"]
    return db, svc, client, tid, client.get(f"/tasks/{tid}").json()["draft"]


def test_offline_gate_finds_three_human_labeled_issue_types():
    cases = json.loads((Path(__file__).parent / "fixtures" / "reader_path_cases.json").read_text())
    for case in cases:
        _, _, client, tid, _ = setup_reader(case["draft"])
        result = client.post(f"/tasks/{tid}/reader-path-review")
        assert result.status_code == 200, (case["name"], result.text)
        payload = result.json()
        assert case["expected_issue"] in {issue["type"] for issue in payload["issues"]}
        expected = [i for i, p in enumerate(case["draft"].split("\n\n"), 1) if p.strip()]
        assert [step["location"]["paragraph_start"] for step in payload["steps"]] == expected
        assert all(step["primary_function"] and step["knowledge_gain"]
                   for step in payload["steps"])


def test_steps_persist_exact_unicode_and_empty_paragraph_positions():
    content = "第一段🙂\n\n\n\n第三段？"
    db, _, client, tid, draft = setup_reader(content)
    result = client.post(f"/tasks/{tid}/reader-path-review").json()
    assert [step["location"]["paragraph_start"] for step in result["steps"]] == [1, 3]
    for row in db.q("SELECT * FROM reader_path_steps ORDER BY paragraph_start"):
        assert content[row["char_start"]:row["char_end"]] == row["quote"]
        assert row["base_revision"] == draft["revision"]


def test_missing_duplicate_or_changed_step_fails_without_partial_review():
    class Incomplete(MockWritingEngine):
        def review_reader_path(self, **kwargs):
            payload = super().review_reader_path(**kwargs)
            payload["steps"] = payload["steps"][:1]
            return payload

    db, _, client, tid, _ = setup_reader("一。\n\n二。", Incomplete())
    response = client.post(f"/tasks/{tid}/reader-path-review")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "READER_PATH_INCOMPLETE"
    assert db.q("SELECT * FROM reviews WHERE analysis_type='reader_path'") == []
    assert db.q("SELECT * FROM reader_path_steps") == []


def test_unverifiable_issue_is_dropped_while_complete_path_remains():
    class BadIssue(MockWritingEngine):
        def review_reader_path(self, **kwargs):
            payload = super().review_reader_path(**kwargs)
            payload["issues"] = [{
                "id": "bad", "type": "reasoning_gap", "severity": "major",
                "paragraph_start": 1, "paragraph_end": 1,
                "quote": "模型编造的正文", "message": "跳跃。",
                "effect": "可能难以跟随。", "goal": "补足中间推理。",
            }]
            return payload

    db, _, client, tid, _ = setup_reader("真实正文。", BadIssue())
    result = client.post(f"/tasks/{tid}/reader-path-review").json()
    assert len(result["steps"]) == 1 and result["issues"] == []
    assert db.q("SELECT * FROM revision_items") == []


def test_reader_path_review_does_not_replace_normal_writing_review():
    _, _, client, tid, _ = setup_reader("这是一个足够长的段落。" * 12 + "\n\n第二段。")
    writing = client.post(f"/tasks/{tid}/review").json()
    path = client.post(f"/tasks/{tid}/reader-path-review").json()
    task = client.get(f"/tasks/{tid}").json()
    assert task["review"]["id"] == writing["id"]
    assert task["review"]["id"] != path["id"]
    assert client.get(f"/tasks/{tid}/revision-worklist").json()["review_id"] == writing["id"]


def test_edit_stales_path_and_blocks_old_issue_actions():
    _, _, client, tid, draft = setup_reader("同一句。\n\n同一句。")
    result = client.post(f"/tasks/{tid}/reader-path-review").json()
    item = result["issues"][0]
    saved = client.patch(f"/drafts/{draft['id']}", json={
        "working_content": draft["working_content"] + "\n\n新段。",
        "expected_revision": draft["revision"],
    })
    assert saved.status_code == 200
    stale = client.get(f"/tasks/{tid}/reader-path-review").json()
    assert stale["stale"] and stale["issues"][0]["status"] == "stale"
    assert client.post(f"/revision-items/{item['revision_item_id']}/dismiss").status_code == 409


def test_path_issue_reject_reopens_and_accept_stales_result():
    db, _, client, tid, draft = setup_reader("重复。\n\n重复。\n\n结尾。")
    review = client.post(f"/tasks/{tid}/reader-path-review").json()
    item = review["issues"][0]
    body = {
        "base_version_id": draft["current_version_id"],
        "expected_revision": draft["revision"], "review_id": review["id"],
        "revision_item_id": item["revision_item_id"],
        "selection": item["location"], "instruction": item["goal"],
    }
    first = client.post(f"/tasks/{tid}/patch", json=body)
    assert first.status_code == 200, first.text
    assert client.get(f"/tasks/{tid}").json()["draft"]["working_content"] == draft["working_content"]
    client.post(f"/patches/{first.json()['patch_id']}/reject")
    assert db.q1("SELECT status FROM revision_items WHERE id=?",
                 (item["revision_item_id"],))["status"] == "open"
    second = client.post(f"/tasks/{tid}/patch", json=body)
    accepted = client.post(f"/patches/{second.json()['patch_id']}/accept")
    assert accepted.status_code == 200, accepted.text
    current = client.get(f"/tasks/{tid}/reader-path-review").json()
    assert current["stale"]
    assert db.q1("SELECT status FROM revision_items WHERE id=?",
                 (item["revision_item_id"],))["status"] == "resolved"


def test_input_limits_fail_explicitly():
    _, _, client, tid, _ = setup_reader("字" * 30001)
    response = client.post(f"/tasks/{tid}/reader-path-review")
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "READER_PATH_INPUT_TOO_LARGE"


def test_v5_database_and_backup_contract_upgrade_to_v6(tmp_path):
    path = tmp_path / "v5.sqlite3"
    db = Database(path)
    db.conn.close()
    with sqlite3.connect(path) as conn:
        conn.execute("DROP INDEX reader_path_steps_review")
        conn.execute("DROP TABLE reader_path_steps")
        conn.execute("ALTER TABLE reviews DROP COLUMN analysis_type")
        conn.execute("PRAGMA user_version=5")
    counts = backup._inspect_sqlite(path)
    assert "reader_path_steps" not in counts
    upgraded = Database(path)
    assert upgraded.q1("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    assert upgraded.q1("SELECT name FROM sqlite_master WHERE name='reader_path_steps'")


def test_v6_backup_contains_path_steps_and_rejects_wrong_analysis_type():
    db, _, client, tid, _ = setup_reader("一。\n\n二。")
    client.post(f"/tasks/{tid}/reader-path-review")
    inspected = backup.inspect_backup(backup.create_backup(db).content)
    assert inspected.summary["table_counts"]["reader_path_steps"] == 2
    db.exec("UPDATE reviews SET analysis_type='writing' WHERE analysis_type='reader_path'")
    try:
        backup.create_backup(db)
        assert False, "reader path steps must point to a reader_path review"
    except backup.BackupError as exc:
        assert "reader_path_steps.review_draft" in str(exc)
