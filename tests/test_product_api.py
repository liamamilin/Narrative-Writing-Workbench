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
