from fastapi.testclient import TestClient

from workbench.api import create_app
from workbench.db import Database
from workbench.engine.mock import MockWritingEngine
from workbench.service import Service


def setup_export():
    db = Database(":memory:")
    svc = Service(db, MockWritingEngine())
    client = TestClient(create_app(svc))
    task = svc.create_task({
        "input_mode": "source_grounded",
        "type": "essay",
        "title": "题目 # 一 /\r\nInjected: x",
        "material": "素材",
        "instruction": "写作",
    })
    generated = svc.generate(task["id"])
    return db, svc, client, task["id"], generated


def test_current_export_preserves_body_and_has_safe_download_headers():
    db, svc, client, tid, generated = setup_export()
    content = "第一段 # 标题\n\n\n空行之间🙂\n尾部  \n"
    saved = svc.autosave(generated["draft_id"], content, generated["revision"])
    before_versions = db.q("SELECT * FROM versions")
    before_operations = db.q("SELECT * FROM writing_operations")

    response = client.get(f"/tasks/{tid}/export", params={
        "format": "md", "expected_revision": saved["revision"],
        "include_title": "false",
    })

    assert response.status_code == 200
    assert response.text == content
    assert response.headers["content-type"].startswith("text/markdown")
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;") and "filename*=UTF-8''" in disposition
    assert "\r" not in disposition and "\n" not in disposition
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert db.q("SELECT * FROM versions") == before_versions
    assert db.q("SELECT * FROM writing_operations") == before_operations


def test_title_is_optional_and_rendered_per_format():
    _, svc, client, tid, generated = setup_export()
    body = svc.task_detail(tid)["draft"]["working_content"]
    md = client.get(f"/tasks/{tid}/export", params={
        "format": "md", "expected_revision": generated["revision"]})
    txt = client.get(f"/tasks/{tid}/export", params={
        "format": "txt", "expected_revision": generated["revision"]})

    assert md.text == "# 题目 \\# 一 / Injected: x\n\n" + body
    assert txt.text == "题目 # 一 / Injected: x\n\n" + body
    assert txt.headers["content-type"].startswith("text/plain")


def test_current_export_requires_fresh_revision_and_valid_format():
    _, svc, client, tid, generated = setup_export()
    assert client.get(f"/tasks/{tid}/export").status_code == 428
    invalid_revision = client.get(f"/tasks/{tid}/export", params={
        "expected_revision": "not-an-integer"})
    assert invalid_revision.status_code == 428
    assert invalid_revision.json()["error"]["code"] == "REVISION_REQUIRED"
    assert client.get(f"/tasks/{tid}/export", params={
        "format": "docx", "expected_revision": generated["revision"]
    }).status_code == 400
    invalid_option = client.get(f"/tasks/{tid}/export", params={
        "expected_revision": generated["revision"], "include_title": "maybe"})
    assert invalid_option.status_code == 400
    assert invalid_option.json()["error"]["code"] == "VALIDATION"

    saved = svc.autosave(generated["draft_id"], "other tab edit", generated["revision"])
    stale = client.get(f"/tasks/{tid}/export", params={
        "expected_revision": generated["revision"]})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_BASE"
    current = client.get(f"/tasks/{tid}/export", params={
        "format": "txt", "expected_revision": saved["revision"],
        "include_title": "false"})
    assert current.text == "other tab edit"


def test_version_export_is_immutable_and_does_not_restore_it():
    db, svc, client, tid, generated = setup_export()
    version_content = svc.get_version(generated["version_id"])["content"]
    saved = svc.autosave(generated["draft_id"], "new working copy", generated["revision"])
    before = svc.task_detail(tid)["draft"]

    response = client.get(f"/versions/{generated['version_id']}/export", params={
        "format": "txt", "include_title": "false"})

    assert response.status_code == 200 and response.text == version_content
    after = svc.task_detail(tid)["draft"]
    assert after["working_content"] == "new working copy"
    assert after["revision"] == saved["revision"] == before["revision"]
    assert after["current_version_id"] == before["current_version_id"]
    assert len(db.q("SELECT * FROM versions")) == 1
    assert client.get("/versions/missing/export").status_code == 404
    assert client.get(f"/versions/{generated['version_id']}/export", params={
        "include_title": "1"}).status_code == 400


def test_task_without_draft_cannot_export():
    db = Database(":memory:")
    svc = Service(db, MockWritingEngine())
    client = TestClient(create_app(svc))
    task = svc.create_task({"input_mode": "topic_only", "topic": "还没有正文"})
    response = client.get(f"/tasks/{task['id']}/export", params={"expected_revision": 0})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_DRAFT"
