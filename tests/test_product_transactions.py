"""Real SQLite concurrency/failure tests; never auto-fill request revisions."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading

import pytest
from fastapi.testclient import TestClient

from workbench.api import create_app
from workbench.db import Database, SCHEMA
from workbench.engine.mock import MockWritingEngine
from workbench.service import ApiError, Service


def setup_task(db=None, engine=None, topic=False):
    db = db or Database(":memory:")
    svc = Service(db, engine or MockWritingEngine())
    c = TestClient(create_app(svc))
    body = ({"input_mode": "topic_only", "topic": "What does waiting change?"} if topic else
            {"type": "essay", "material": "A repaired clock waits on the table.", "instruction": "Write clearly."})
    tid = c.post("/tasks", json=body).json()["id"]
    g = c.post(f"/tasks/{tid}/generate").json()
    assert "version_id" in g, g
    return db, svc, c, tid, g


def proposal(c, tid):
    draft = c.get(f"/tasks/{tid}").json()["draft"]
    r = c.post(f"/tasks/{tid}/patch", json={
        "base_version_id": draft["current_version_id"], "expected_revision": draft["revision"],
        "selection": {"paragraph_start": 1, "paragraph_end": 1}, "instruction": "shorter"})
    assert r.status_code == 200, r.text
    return r.json()["patch_id"]


def test_concurrent_accept_is_one_commit():
    db, svc, c, tid, _ = setup_task()
    pid = proposal(c, tid)
    barrier = threading.Barrier(2)
    def accept():
        barrier.wait(timeout=5)
        try:
            return svc.accept_patch(pid)["status"]
        except ApiError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(accept) for _ in range(2)]
        assert sorted(f.result(timeout=5) for f in futures) == ["STALE_PATCH", "accepted"]
    assert len(db.q("SELECT * FROM versions WHERE source_type='patch'")) == 1


def test_accept_reject_race_has_one_consistent_outcome():
    db, svc, c, tid, g = setup_task()
    pid = proposal(c, tid)
    barrier = threading.Barrier(2)
    def run(fn):
        barrier.wait(timeout=5)
        try: return fn(pid)["status"]
        except ApiError as exc: return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(run, fn) for fn in (svc.accept_patch, svc.reject_patch)]
        results = [f.result(timeout=5) for f in jobs]
    assert results.count("STALE_PATCH") == 1
    p = db.q1("SELECT * FROM proposed_patches WHERE id=?", (pid,))
    d = c.get(f"/tasks/{tid}").json()["draft"]
    assert (d["working_content"] != g["content"]) == (p["status"] == "accepted")


@pytest.mark.parametrize("table,event", [("versions", "INSERT"), ("drafts", "UPDATE"),
                                         ("proposed_patches", "UPDATE")])
def test_accept_rolls_back_each_failed_write(table, event):
    db, svc, c, tid, _ = setup_task()
    pid = proposal(c, tid)
    before = {t: db.q(f"SELECT * FROM {t}") for t in ("drafts", "versions", "proposed_patches")}
    db.exec(f"CREATE TRIGGER inject_failure BEFORE {event} ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    with pytest.raises(sqlite3.IntegrityError): svc.accept_patch(pid)
    assert {t: db.q(f"SELECT * FROM {t}") for t in before} == before
    assert not db.conn.in_transaction


def test_missing_and_invalid_revision_are_rejected():
    _, _, c, tid, g = setup_task()
    for revision in (None, True, -1, "1"):
        r = c.patch(f"/drafts/{g['draft_id']}", json={"working_content": "lost?", "expected_revision": revision})
        assert r.status_code == 428
    for endpoint in (f"/tasks/{tid}/checkpoint", f"/versions/{g['version_id']}/restore", f"/tasks/{tid}/generate"):
        assert c.post(endpoint).status_code == 428
    assert c.get(f"/tasks/{tid}").json()["draft"]["working_content"] == g["content"]


def test_late_autosave_cannot_undo_an_accepted_patch():
    _, _, c, tid, g = setup_task()
    pid = proposal(c, tid)
    accepted = c.post(f"/patches/{pid}/accept").json()
    assert c.patch(f"/drafts/{g['draft_id']}", json={
        "working_content": "late old content", "expected_revision": g["revision"]}).status_code == 409
    assert c.get(f"/tasks/{tid}").json()["draft"]["working_content"] == accepted["content"]


def test_change_outside_selection_invalidates_proposal():
    _, _, c, tid, g = setup_task()
    pid = proposal(c, tid)
    changed = g["content"] + "\n\nManual paragraph."
    assert c.patch(f"/drafts/{g['draft_id']}", json={
        "working_content": changed, "expected_revision": g["revision"]}).status_code == 200
    assert c.post(f"/patches/{pid}/accept").status_code == 409
    assert c.get(f"/tasks/{tid}").json()["draft"]["working_content"] == changed


def test_accept_preserves_uncheckpointed_working_copy():
    db, _, c, tid, g = setup_task()
    changed = g["content"] + "\n\nKeep this manual addition."
    c.patch(f"/drafts/{g['draft_id']}", json={"working_content": changed, "expected_revision": g["revision"]})
    pid = proposal(c, tid)
    assert c.post(f"/patches/{pid}/accept").status_code == 200
    checkpoint = db.q1("SELECT * FROM versions WHERE source_type='manual_checkpoint'")
    assert checkpoint["content"] == changed
    assert checkpoint["engine_plan_id"] == db.q1("SELECT * FROM versions WHERE id=?", (g["version_id"],))["engine_plan_id"]


def test_late_generation_preserves_manual_edit_and_generated_artifact():
    db, svc, c, tid, g = setup_task()
    class Delayed(MockWritingEngine):
        started = threading.Event()
        release = threading.Event()
        def generate(self, **kw):
            result = super().generate(**kw)
            self.started.set()
            assert self.release.wait(timeout=5)
            return result
    engine = Delayed()
    svc.engine = engine
    with ThreadPoolExecutor(max_workers=1) as pool:
        job = pool.submit(svc.generate, tid, {"expected_revision": g["revision"]})
        assert engine.started.wait(timeout=5)
        try:
            svc.autosave(g["draft_id"], "Manual edit during generation", g["revision"])
        finally: engine.release.set()
        with pytest.raises(ApiError, match="正文已") as exc:
            job.result(timeout=5)
        assert exc.value.code == "STALE_BASE"
    assert c.get(f"/tasks/{tid}").json()["draft"]["working_content"] == "Manual edit during generation"
    assert len(db.q("SELECT * FROM generation_results WHERE accepted_version_id IS NULL")) == 1
    assert len(db.q("SELECT * FROM versions")) == 1


def test_restore_recovers_plan_and_meaning_not_latest_attempt():
    db, svc, c, tid, first = setup_task(topic=True)
    meaning = svc.meaning_summary(tid)
    v1 = svc.get_version(first["version_id"])
    second = c.post(f"/tasks/{tid}/rediscover-angle", json={"expected_revision": first["revision"]}).json()
    assert svc.meaning_summary(tid) != meaning
    restored = c.post(f"/versions/{first['version_id']}/restore", json={"expected_revision": second["revision"]}).json()
    vr = svc.get_version(restored["version_id"])
    assert vr["engine_plan_id"] == v1["engine_plan_id"]
    assert vr["restore_source_version_id"] == first["version_id"]
    assert svc.meaning_summary(tid) == meaning
    svc.engine.fail_writer = True
    assert c.post(f"/tasks/{tid}/rediscover-angle", json={"expected_revision": restored["revision"]}).status_code == 500
    assert svc.meaning_summary(tid) == meaning


def test_review_is_stale_after_text_or_goal_changes():
    _, _, c, tid, g = setup_task()
    review = c.post(f"/tasks/{tid}/review").json()
    assert not review["stale"]
    c.patch(f"/tasks/{tid}", json={"instruction": "Different intent"})
    assert c.get(f"/tasks/{tid}").json()["review"]["stale"]
    r = c.post(f"/tasks/{tid}/patch", json={
        "expected_revision": g["revision"], "review_id": review["id"],
        "selection": {"paragraph_start": 1, "paragraph_end": 1}, "instruction": "shorter"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_REVIEW"


def test_legacy_migration_keeps_unknown_plan_unknown(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO drafts VALUES('d','t','v','legacy content','old')")
    conn.execute("INSERT INTO versions VALUES('v','d',NULL,'legacy content','generation',NULL,'old')")
    conn.commit(); conn.close()
    for _ in range(2):
        db = Database(path)
        assert db.q1("SELECT * FROM drafts")["revision"] == 0
        version = db.q1("SELECT * FROM versions")
        assert version["content"] == "legacy content" and version["engine_plan_id"] is None
        db.conn.close()


def test_import_is_atomic_and_does_not_call_writer():
    engine = MockWritingEngine()
    engine.fail_writer = True
    db = Database(":memory:")
    svc = Service(db, engine)
    content = '原稿第一段。\n\n保留的结尾。'
    tid = svc.create_task({"input_mode": "draft_revision", "type": "essay", "material": content})["id"]
    detail = svc.task_detail(tid)
    assert detail["draft"]["working_content"] == content
    v = svc.get_version(detail["draft"]["current_version_id"])
    assert v["source_type"] == "manual_checkpoint" and v["engine_plan_id"] is None
    before = len(svc.db.q("SELECT * FROM tasks"))
    db.exec("CREATE TRIGGER fail_import BEFORE INSERT ON versions BEGIN SELECT RAISE(ABORT, 'fail import'); END")
    with pytest.raises(sqlite3.IntegrityError):
        svc.create_task({"input_mode": "draft_revision", "type": "essay", "material": content})
    assert len(db.q("SELECT * FROM tasks")) == before
    assert len(db.q("SELECT * FROM sources")) == 1


def test_migration_recovers_unambiguous_import_and_never_replaces_existing(tmp_path):
    path = tmp_path / "import.db"
    db = Database(path)
    svc = Service(db, MockWritingEngine())
    tid = svc.create_task({"input_mode": "source_grounded", "type": "essay", "material": "旧版入口保存的原稿。"})["id"]
    db.exec("UPDATE tasks SET input_mode='draft_revision' WHERE id=?", (tid,))
    db.exec("PRAGMA user_version=1")
    db.conn.close()
    upgraded = Database(path)
    draft = upgraded.q1("SELECT * FROM drafts WHERE task_id=?", (tid,))
    assert draft["working_content"] == "旧版入口保存的原稿。" and draft["revision"] == 1
    upgraded.conn.close()
    again = Database(path)
    assert again.q1("SELECT * FROM drafts WHERE task_id=?", (tid,)) == draft
    assert len(again.q("SELECT * FROM versions")) == 1


def test_changing_locks_invalidates_existing_proposal():
    db, svc, c, tid, g = setup_task()
    pid = proposal(c, tid)
    c.patch(f'/tasks/{tid}', json={'config': {'locks': {'facts': True, 'wording': True}}})
    r = c.post(f'/patches/{pid}/accept')
    assert r.status_code == 409 and r.json()['error']['code'] == 'LOCK_CONFLICT'
    assert c.get(f'/tasks/{tid}').json()['draft']['working_content'] == g['content']
    assert db.q1('SELECT status FROM proposed_patches WHERE id=?', (pid,))['status'] == 'proposed'


def test_invalid_goal_config_never_partially_changes_instruction():
    _, _, c, tid, _ = setup_task()
    before = c.get(f'/tasks/{tid}').json()['instruction']
    r = c.patch(f'/tasks/{tid}', json={'instruction': 'must not persist', 'config': {'immersion': 'invalid'}})
    assert r.status_code == 400
    assert c.get(f'/tasks/{tid}').json()['instruction'] == before
