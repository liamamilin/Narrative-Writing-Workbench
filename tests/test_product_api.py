"""Product V0 API + safety tests (docs/narrative-writing-product-v0-spec)."""

from __future__ import annotations

import pytest
from conftest import RevisionClient as TestClient

from workbench.api import create_app
from workbench.db import Database
from workbench.engine import GenerationFailed, GenerateResult
from workbench.engine.mock import MockWritingEngine
from workbench.service import Service


class BrokenEngine(MockWritingEngine):
    """generate always fails — used to prove failure safety."""

    def generate(self, **kw):
        raise GenerationFailed("simulated provider outage")


@pytest.fixture()
def client():
    return TestClient(create_app(Service(Database(":memory:"))))


@pytest.fixture()
def broken_client():
    svc = Service(Database(":memory:"), engine=BrokenEngine())
    return TestClient(create_app(svc))


def make_task(c, **over):
    body = {"type": "fiction_scene", "title": "Dinner",
            "instruction": "父亲不要直接表达支持。",
            "material": "年夜饭上,父亲给我夹了一筷子鱼腹。",
            "config": {"expected_language": "zh", "target_length": 800,
                       "immersion": "high", "explicitness": "low",
                       "intensity": "medium",
                       "locks": {"facts": True, "core_meaning": True}}}
    body.update(over)
    r = c.post("/tasks", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# --------------------------------------------------------------- CRUD ----

def test_project_and_source_creation(client):
    p = client.post("/projects", json={"name": "Essays"}).json()
    assert p["name"] == "Essays"
    s = client.post(f"/projects/{p['id']}/sources",
                    json={"title": "note", "type": "note", "content": "abc"}).json()
    assert s["project_id"] == p["id"]
    assert client.get(f"/projects/{p['id']}").json()["sources"][0]["id"] == s["id"]


def test_create_task_validation(client):
    assert client.post("/tasks", json={"type": "nope"}).status_code == 400
    assert client.post("/tasks", json={"type": "essay", "instruction": "",
                                       "material": ""}).status_code == 400
    assert client.post("/tasks", json={"type": "essay", "instruction": "x",
                                       "config": {"immersion": "extreme"}}).status_code == 400


def test_task_config_and_locks_persist(client):
    tid = make_task(client)
    t = client.get(f"/tasks/{tid}").json()
    assert t["config"]["locks"]["facts"] is True
    assert t["config"]["target_length"] == 800
    client.patch(f"/tasks/{tid}", json={"config": {"locks": {"facts": False}}})
    assert client.get(f"/tasks/{tid}").json()["config"]["locks"]["facts"] is False


def test_unknown_ids_404(client):
    assert client.get("/tasks/nope").status_code == 404
    assert client.get("/projects/nope").status_code == 404


def test_task_list_is_complete_ordered_and_keeps_status(client):
    assert client.get("/tasks").json() == {"tasks": []}
    ids = [make_task(client, title=f"Task {i}") for i in range(51)]
    client.patch(f"/tasks/{ids[0]}", json={"status": "done"})
    client.patch(f"/tasks/{ids[1]}", json={"status": "failed"})
    db = client.app.state.service.db
    db.exec("UPDATE tasks SET updated_at=? WHERE id=?", ("2099-01-01T00:00:00+00:00", ids[0]))
    db.exec("UPDATE tasks SET updated_at=? WHERE id=?", ("2098-01-01T00:00:00+00:00", ids[1]))

    rows = client.get("/tasks").json()["tasks"]
    assert len(rows) == 51
    assert {row["id"] for row in rows} == set(ids)
    assert rows[0]["id"] == ids[0]
    assert rows[0]["status"] == "done"
    assert {row["status"] for row in rows} >= {"draft", "failed", "done"}


def test_delete_task_removes_writing_artifacts_but_keeps_project_sources(client):
    project = client.post("/projects", json={"name": "Collection"}).json()
    source = client.post(f"/projects/{project['id']}/sources", json={
        "title": "Shared note", "type": "note", "content": "Shared evidence.",
    }).json()
    tid = make_task(client, type="essay", project_id=project["id"],
                    source_ids=[source["id"]])
    generated = client.post(f"/tasks/{tid}/generate", json={})
    assert generated.status_code == 200, generated.text
    task = client.get(f"/tasks/{tid}").json()
    draft = task["draft"]
    assert client.post(f"/tasks/{tid}/review").status_code == 200
    assert client.post(f"/tasks/{tid}/reader-path-review").status_code == 200
    assert client.post(f"/tasks/{tid}/preserved-spans", json={
        "expected_revision": draft["revision"],
        "selection": {"paragraph_start": 1, "paragraph_end": 1},
    }).status_code == 200

    db = client.app.state.service.db
    assert db.q("SELECT * FROM versions WHERE draft_id=?", (draft["id"],))
    assert db.q("SELECT * FROM writing_operations WHERE task_id=?", (tid,))
    assert db.q("SELECT * FROM operation_events WHERE operation_id IN "
                "(SELECT id FROM writing_operations WHERE task_id=?)", (tid,))

    deleted = client.delete(f"/tasks/{tid}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert client.get(f"/tasks/{tid}").status_code == 404
    project_after = client.get(f"/projects/{project['id']}").json()
    assert project_after["tasks"] == []
    assert source["id"] in {row["id"] for row in project_after["sources"]}
    assert db.q1("SELECT id FROM sources WHERE id=?", (source["id"],))
    assert db.q("SELECT * FROM task_sources WHERE task_id=?", (tid,)) == []
    assert db.q("SELECT * FROM writing_configs WHERE task_id=?", (tid,)) == []
    assert db.q("SELECT * FROM drafts WHERE task_id=?", (tid,)) == []
    assert db.q("SELECT * FROM versions WHERE draft_id=?", (draft["id"],)) == []
    assert db.q("SELECT * FROM proposed_patches WHERE draft_id=?", (draft["id"],)) == []
    assert db.q("SELECT * FROM reviews WHERE draft_id=?", (draft["id"],)) == []
    assert db.q("SELECT * FROM revision_items WHERE draft_id=?", (draft["id"],)) == []
    assert db.q("SELECT * FROM preserved_spans WHERE draft_id=?", (draft["id"],)) == []
    assert db.q("SELECT * FROM claim_checks WHERE task_id=?", (tid,)) == []
    assert db.q("SELECT * FROM claim_links WHERE draft_id=?", (draft["id"],)) == []
    assert db.q("SELECT * FROM reader_path_steps WHERE draft_id=?", (draft["id"],)) == []
    assert db.q("SELECT * FROM engine_plans WHERE task_id=?", (tid,)) == []
    assert db.q("SELECT * FROM meaning_discoveries WHERE task_id=?", (tid,)) == []
    assert db.q("SELECT * FROM generation_results WHERE task_id=?", (tid,)) == []
    assert db.q("SELECT * FROM writing_operations WHERE task_id=?", (tid,)) == []
    assert db.q("SELECT e.* FROM operation_events e LEFT JOIN writing_operations o "
                "ON o.id=e.operation_id WHERE o.id IS NULL") == []
    assert db.q("SELECT r.* FROM operation_records r LEFT JOIN writing_operations o "
                "ON o.id=r.operation_id WHERE o.id IS NULL") == []
    assert client.get("/backups/export").status_code == 200


def test_delete_task_releases_linked_idea_and_cleans_private_source(client):
    idea = client.post("/ideas", json={"topic": "等待为什么改变人"}).json()["idea"]
    task = client.post("/tasks", json={
        "input_mode": "topic_only", "topic": idea["topic"], "idea_id": idea["id"],
    }).json()
    private = client.post(f"/tasks/{task['id']}/sources", json={
        "title": "Private", "content": "Only used by this task.",
    }).json()

    deleted = client.delete(f"/tasks/{task['id']}").json()
    assert deleted["returned_ideas"] == 1
    assert deleted["removed_unlinked_sources"] == 1
    db = client.app.state.service.db
    assert db.q1("SELECT id FROM sources WHERE id=?", (private["id"],)) is None
    assert db.q1("SELECT task_id,status FROM ideas WHERE id=?", (idea["id"],)) == {
        "task_id": None, "status": "to_write"}


def test_delete_running_task_is_rejected_without_partial_cleanup(client):
    tid = make_task(client)
    db = client.app.state.service.db
    db.exec(
        "INSERT INTO writing_operations(id,task_id,kind,process_id,status,stage,"
        "started_at,snapshot_json) VALUES(?,?,?,?,?,?,?,?)",
        ("op_running", tid, "generate", "test", "running", "queued", "now", "{}"))

    response = client.delete(f"/tasks/{tid}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_RUNNING"
    assert client.get(f"/tasks/{tid}").status_code == 200
    assert db.q1("SELECT task_id FROM writing_configs WHERE task_id=?", (tid,))


# -------------------------------------------------------- project delete ----

def test_delete_project_cascades_tasks_sources_and_artifacts(client):
    project = client.post("/projects", json={"name": "Collection"}).json()
    source = client.post(f"/projects/{project['id']}/sources", json={
        "title": "Shared note", "type": "note", "content": "Shared evidence.",
    }).json()
    tid = make_task(client, type="essay", project_id=project["id"],
                    source_ids=[source["id"]])
    generated = client.post(f"/tasks/{tid}/generate", json={})
    assert generated.status_code == 200, generated.text
    task = client.get(f"/tasks/{tid}").json()
    draft = task["draft"]
    assert client.post(f"/tasks/{tid}/review").status_code == 200
    assert client.post(f"/tasks/{tid}/reader-path-review").status_code == 200

    db = client.app.state.service.db

    deleted = client.delete(f"/projects/{project['id']}")
    assert deleted.status_code == 200
    body = deleted.json()
    assert body["deleted"] is True
    assert body["deleted_tasks"] == 1
    assert body["removed_sources"] >= 1
    assert client.get(f"/projects/{project['id']}").status_code == 404
    assert client.get(f"/tasks/{tid}").status_code == 404
    assert db.q1("SELECT id FROM sources WHERE id=?", (source["id"],)) is None
    assert db.q("SELECT * FROM task_sources WHERE source_id=?", (source["id"],)) == []
    assert db.q("SELECT * FROM tasks WHERE project_id=?", (project["id"],)) == []
    assert db.q("SELECT * FROM sources WHERE project_id=?", (project["id"],)) == []
    assert db.q("SELECT * FROM drafts WHERE task_id=?", (tid,)) == []
    assert db.q("SELECT * FROM versions WHERE draft_id=?", (draft["id"],)) == []
    assert db.q("SELECT * FROM proposed_patches WHERE draft_id=?", (draft["id"],)) == []
    assert db.q("SELECT * FROM reviews WHERE draft_id=?", (draft["id"],)) == []
    assert db.q("SELECT * FROM writing_operations WHERE task_id=?", (tid,)) == []
    assert db.q("SELECT e.* FROM operation_events e LEFT JOIN writing_operations o "
                "ON o.id=e.operation_id WHERE o.id IS NULL") == []
    assert client.get("/backups/export").status_code == 200


def test_delete_project_releases_linked_ideas(client):
    project = client.post("/projects", json={"name": "Topics"}).json()
    idea = client.post("/ideas", json={"topic": "等待为什么改变人"}).json()["idea"]
    task = client.post("/tasks", json={
        "input_mode": "topic_only", "topic": idea["topic"], "idea_id": idea["id"],
        "project_id": project["id"],
    }).json()

    deleted = client.delete(f"/projects/{project['id']}").json()
    assert deleted["returned_ideas"] == 1
    db = client.app.state.service.db
    assert client.get(f"/tasks/{task['id']}").status_code == 404
    assert db.q1("SELECT task_id,status FROM ideas WHERE id=?", (idea["id"],)) == {
        "task_id": None, "status": "to_write"}


def test_delete_running_project_is_rejected_without_partial_cleanup(client):
    project = client.post("/projects", json={"name": "Running"}).json()
    tid = make_task(client, project_id=project["id"])
    db = client.app.state.service.db
    db.exec(
        "INSERT INTO writing_operations(id,task_id,kind,process_id,status,stage,"
        "started_at,snapshot_json) VALUES(?,?,?,?,?,?,?,?)",
        ("op_running", tid, "generate", "test", "running", "queued", "now", "{}"))

    response = client.delete(f"/projects/{project['id']}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_RUNNING"
    assert client.get(f"/projects/{project['id']}").status_code == 200
    assert client.get(f"/tasks/{tid}").status_code == 200


def test_delete_project_cleans_cross_task_source_links(client):
    project_a = client.post("/projects", json={"name": "A"}).json()
    project_b = client.post("/projects", json={"name": "B"}).json()
    source = client.post(f"/projects/{project_a['id']}/sources", json={
        "title": "Shared", "type": "note", "content": "cross-project evidence.",
    }).json()
    # Task in project B references a source owned by project A.
    tid_b = make_task(client, project_id=project_b["id"], source_ids=[source["id"]])

    deleted = client.delete(f"/projects/{project_a['id']}")
    assert deleted.status_code == 200
    db = client.app.state.service.db
    assert db.q1("SELECT id FROM sources WHERE id=?", (source["id"],)) is None
    assert db.q("SELECT * FROM task_sources WHERE source_id=?", (source["id"],)) == []
    # Task B survives; the link to the deleted source is simply gone.
    assert client.get(f"/tasks/{tid_b}").status_code == 200
    assert client.get("/backups/export").status_code == 200


# ---------------------------------------------------------- generation ----

def test_generate_creates_version_and_draft(client):
    tid = make_task(client)
    g = client.post(f"/tasks/{tid}/generate").json()
    assert g["status"] == "completed"
    t = client.get(f"/tasks/{tid}").json()
    assert t["draft"]["working_content"] == g["content"]
    vs = client.get(f"/drafts/{g['draft_id']}/versions").json()["versions"]
    assert len(vs) == 1 and vs[0]["source_type"] == "generation"


def test_generate_failure_preserves_existing_draft(broken_client):
    tid = make_task(broken_client)
    r = broken_client.post(f"/tasks/{tid}/generate")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "GENERATION_FAILED"
    assert r.json()["error"]["retryable"] is True
    assert broken_client.get(f"/tasks/{tid}").json()["draft"] is None
    assert broken_client.get(f"/tasks/{tid}").json()["status"] == "failed"


def test_regenerate_failure_keeps_old_draft(client, broken_client):
    # good draft exists, then engine breaks -> old content untouched
    tid = make_task(client)
    g = client.post(f"/tasks/{tid}/generate").json()
    svc = broken_client.app.state.service
    svc.db = client.app.state.service.db  # share db, keep broken engine
    r = broken_client.post(f"/tasks/{tid}/generate")
    assert r.status_code == 500
    assert client.get(f"/tasks/{tid}").json()["draft"]["working_content"] == g["content"]


def test_writing_map_is_product_safe(client):
    tid = make_task(client)
    client.post(f"/tasks/{tid}/generate")
    wm = client.get(f"/tasks/{tid}/writing-map").json()
    assert wm["beats"]
    joined = str(wm)
    for leak in ("wir_version", "reader_transition", "chain_of_thought",
                 "private", "reasoning"):
        assert leak not in joined


# --------------------------------------------------------------- patch ----

def test_patch_propose_does_not_touch_draft(client):
    tid = make_task(client)
    g = client.post(f"/tasks/{tid}/generate").json()
    pp = client.post(f"/tasks/{tid}/patch", json={
        "base_version_id": g["version_id"],
        "selection": {"paragraph_start": 2, "paragraph_end": 2},
        "instruction": "Make this shorter."}).json()
    assert pp["status"] == "proposed"
    assert client.get(f"/tasks/{tid}").json()["draft"]["working_content"] == g["content"]


def test_patch_accept_creates_version_and_splices(client):
    tid = make_task(client)
    g = client.post(f"/tasks/{tid}/generate").json()
    pp = client.post(f"/tasks/{tid}/patch", json={
        "base_version_id": g["version_id"],
        "selection": {"paragraph_start": 2, "paragraph_end": 2},
        "instruction": "Make this shorter."}).json()
    before = g["content"].split("\n\n")
    a = client.post(f"/patches/{pp['patch_id']}/accept").json()
    after = a["content"].split("\n\n")
    assert after[0] == before[0] and after[-1] == before[-1]  # local only
    vs = client.get(f"/drafts/{g['draft_id']}/versions").json()["versions"]
    assert vs[-1]["source_type"] == "patch"


def test_patch_reject_leaves_draft_unchanged(client):
    tid = make_task(client)
    g = client.post(f"/tasks/{tid}/generate").json()
    pp = client.post(f"/tasks/{tid}/patch", json={
        "base_version_id": g["version_id"],
        "selection": {"paragraph_start": 3, "paragraph_end": 3},
        "instruction": "Make this shorter."}).json()
    client.post(f"/patches/{pp['patch_id']}/reject")
    assert client.get(f"/tasks/{tid}").json()["draft"]["working_content"] == g["content"]


def test_patch_lock_conflict_is_safe(client):
    tid = make_task(client)
    g = client.post(f"/tasks/{tid}/generate").json()
    r = client.post(f"/tasks/{tid}/patch", json={
        "base_version_id": g["version_id"],
        "selection": {"paragraph_start": 1, "paragraph_end": 1},
        "instruction": "please invent new events",
        "locks": {"facts": True}})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "LOCK_CONFLICT"
    assert client.get(f"/tasks/{tid}").json()["draft"]["working_content"] == g["content"]


def test_stale_base_patch_rejected(client):
    tid = make_task(client)
    g = client.post(f"/tasks/{tid}/generate").json()
    r = client.post(f"/tasks/{tid}/patch", json={
        "base_version_id": "ver_bogus",
        "selection": {"paragraph_start": 1, "paragraph_end": 1},
        "instruction": "x"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_BASE"


def test_double_accept_blocked(client):
    tid = make_task(client)
    g = client.post(f"/tasks/{tid}/generate").json()
    pp = client.post(f"/tasks/{tid}/patch", json={
        "base_version_id": g["version_id"],
        "selection": {"paragraph_start": 2, "paragraph_end": 2},
        "instruction": "Make this shorter."}).json()
    client.post(f"/patches/{pp['patch_id']}/accept")
    assert client.post(f"/patches/{pp['patch_id']}/accept").status_code == 409


def test_try_again_makes_second_proposal(client):
    tid = make_task(client)
    g = client.post(f"/tasks/{tid}/generate").json()
    body = {"base_version_id": g["version_id"],
            "selection": {"paragraph_start": 2, "paragraph_end": 2},
            "instruction": "Make this shorter."}
    p1 = client.post(f"/tasks/{tid}/patch", json=body).json()
    p2 = client.post(f"/tasks/{tid}/patch", json=body).json()
    assert p1["patch_id"] != p2["patch_id"]


# ------------------------------------------------------------ versions ----

def test_restore_creates_new_version_and_is_reversible(client):
    tid = make_task(client)
    g = client.post(f"/tasks/{tid}/generate").json()
    pp = client.post(f"/tasks/{tid}/patch", json={
        "base_version_id": g["version_id"],
        "selection": {"paragraph_start": 2, "paragraph_end": 2},
        "instruction": "Make this shorter."}).json()
    client.post(f"/patches/{pp['patch_id']}/accept")
    vs = client.get(f"/drafts/{g['draft_id']}/versions").json()["versions"]
    client.post(f"/versions/{vs[0]['id']}/restore")
    assert client.get(f"/tasks/{tid}").json()["draft"]["working_content"] == g["content"]
    # reversible: the patched version still exists in history
    vs2 = client.get(f"/drafts/{g['draft_id']}/versions").json()["versions"]
    assert any(v["source_type"] == "patch" for v in vs2)
    assert vs2[-1]["source_type"] == "restore"


def test_autosave_does_not_version(client):
    tid = make_task(client)
    g = client.post(f"/tasks/{tid}/generate").json()
    client.patch(f"/drafts/{g['draft_id']}", json={"working_content": "手改内容"})
    t = client.get(f"/tasks/{tid}").json()
    assert t["draft"]["working_content"] == "手改内容"
    vs = client.get(f"/drafts/{g['draft_id']}/versions").json()["versions"]
    assert len(vs) == 1


def test_checkpoint_creates_manual_version(client):
    tid = make_task(client)
    g = client.post(f"/tasks/{tid}/generate").json()
    client.patch(f"/drafts/{g['draft_id']}", json={"working_content": "编辑中"})
    client.post(f"/tasks/{tid}/checkpoint")
    vs = client.get(f"/drafts/{g['draft_id']}/versions").json()["versions"]
    assert vs[-1]["source_type"] == "manual_checkpoint"


# --------------------------------------------------------------- review ----

def test_review_positions_and_fixable(client):
    tid = make_task(client)
    client.post(f"/tasks/{tid}/generate")
    rev = client.post(f"/tasks/{tid}/review").json()
    assert set(rev["summary"]) == {"progression", "meaning_density", "immersion",
                                   "restraint", "coherence"}
    for issue in rev["issues"]:
        assert set(issue) >= {"id", "location", "type", "message", "fixable"}
        assert issue["location"]["paragraph_start"] >= 1


def test_review_without_draft_409(client):
    tid = make_task(client)
    assert client.post(f"/tasks/{tid}/review").status_code == 409
