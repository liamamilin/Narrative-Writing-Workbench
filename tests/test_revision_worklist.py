"""Product V0.4 revision worklist and preserved-passage acceptance tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
import json
import sqlite3
import threading
import zipfile

import pytest
from fastapi.testclient import TestClient

from workbench import backup
from workbench.api import create_app
from workbench.backup import inspect_backup
from workbench.db import Database, SCHEMA_VERSION
from workbench.engine.mock import MockWritingEngine
from workbench.service import ApiError, Service


def setup_worklist(tmp_path=None):
    db = Database(":memory:" if tmp_path is None else tmp_path / "worklist.db")
    svc = Service(db, MockWritingEngine())
    client = TestClient(create_app(svc))
    content = (
        "This deliberately long opening paragraph repeats its explanation until the reader "
        "has no room left to infer what the scene means, and it continues beyond the review threshold."
        "\n\nKeep this exact second paragraph.\n\nA final paragraph remains here."
    )
    tid = client.post("/tasks", json={
        "input_mode": "draft_revision", "type": "essay", "title": "Revision",
        "material": content, "instruction": "Keep the meaning concrete.",
    }).json()["id"]
    detail = client.get(f"/tasks/{tid}").json()
    return db, svc, client, tid, detail["draft"]


def review_item(client, tid):
    response = client.post(f"/tasks/{tid}/review")
    assert response.status_code == 200, response.text
    review = response.json()
    assert review["issues"] and review["issues"][0]["status"] == "open"
    return review, review["issues"][0]


def propose_item(client, tid, draft, review, item):
    return client.post(f"/tasks/{tid}/patch", json={
        "base_version_id": draft["current_version_id"],
        "expected_revision": draft["revision"],
        "review_id": review["id"],
        "revision_item_id": item["revision_item_id"],
        "selection": item["location"],
        "instruction": item["goal"],
    })


def test_review_creates_anchored_worklist_and_skip_changes_no_text():
    db, _, client, tid, draft = setup_worklist()
    review, item = review_item(client, tid)
    worklist = client.get(f"/tasks/{tid}/revision-worklist").json()
    assert worklist["review_id"] == review["id"] and not worklist["stale"]
    assert item["quote"] == draft["working_content"].split("\n\n")[0]
    row = db.q1("SELECT * FROM revision_items WHERE id=?", (item["revision_item_id"],))
    assert row["content_hash"] == sha256(draft["working_content"].encode()).hexdigest()
    assert (row["char_start"], row["char_end"]) == (0, len(item["quote"]))

    skipped = client.post(f"/revision-items/{item['revision_item_id']}/dismiss")
    assert skipped.json()["status"] == "dismissed"
    assert client.get(f"/tasks/{tid}").json()["draft"]["working_content"] == draft["working_content"]


def test_worklist_shows_three_highest_open_items_and_advances_after_skip():
    class FourIssues(MockWritingEngine):
        def review(self, **kwargs):
            severities = ["fatal", "major", "moderate", "minor"]
            issues = [{
                "id": f"issue_{i}",
                "location": {"paragraph_start": min(i, 3), "paragraph_end": min(i, 3)},
                "type": "issue", "severity": severity, "message": f"Issue {i}",
                "effect": f"Effect {i}", "goal": "Make this shorter.", "fixable": True,
            } for i, severity in enumerate(severities, 1)]
            return {"summary": {"progression": "good"}, "issues": issues}

    _, svc, client, tid, _ = setup_worklist()
    svc.engine = FourIssues()
    review = client.post(f"/tasks/{tid}/review").json()
    assert [item["severity"] for item in review["issues"]] == ["fatal", "major", "moderate"]
    assert review["total_issue_count"] == 4
    client.post(f"/revision-items/{review['issues'][0]['revision_item_id']}/dismiss")
    advanced = client.get(f"/tasks/{tid}/revision-worklist").json()
    assert [item["severity"] for item in advanced["items"]] == ["major", "moderate", "minor"]
    assert advanced["remaining_issue_count"] == 3


def test_preserved_overlap_rejects_proposal_without_partial_rows():
    db, _, client, tid, draft = setup_worklist()
    keep = client.post(f"/tasks/{tid}/preserved-spans", json={
        "expected_revision": draft["revision"],
        "selection": {"paragraph_start": 1, "paragraph_end": 1},
    })
    assert keep.status_code == 200
    review, item = review_item(client, tid)
    response = propose_item(client, tid, draft, review, item)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PRESERVED_TEXT_CONFLICT"
    assert db.q("SELECT * FROM proposed_patches") == []
    assert db.q1("SELECT status FROM revision_items WHERE id=?",
                 (item["revision_item_id"],))["status"] == "open"


def test_preserve_added_after_proposal_blocks_accept_transaction():
    db, _, client, tid, draft = setup_worklist()
    review, item = review_item(client, tid)
    proposed = propose_item(client, tid, draft, review, item).json()
    client.post(f"/tasks/{tid}/preserved-spans", json={
        "expected_revision": draft["revision"], "selection": item["location"],
    })
    before_versions = len(db.q("SELECT * FROM versions"))
    accepted = client.post(f"/patches/{proposed['patch_id']}/accept")
    assert accepted.status_code == 422
    assert accepted.json()["error"]["code"] == "PRESERVED_TEXT_CONFLICT"
    assert len(db.q("SELECT * FROM versions")) == before_versions
    assert db.q1("SELECT status FROM proposed_patches WHERE id=?",
                 (proposed["patch_id"],))["status"] == "proposed"
    assert db.q1("SELECT status FROM revision_items WHERE id=?",
                 (item["revision_item_id"],))["status"] == "proposed"


def test_linked_patch_reject_reopens_then_accept_resolves_and_rebases_preserve():
    db, _, client, tid, draft = setup_worklist()
    kept = client.post(f"/tasks/{tid}/preserved-spans", json={
        "expected_revision": draft["revision"],
        "selection": {"paragraph_start": 2, "paragraph_end": 2},
    }).json()
    review, item = review_item(client, tid)

    first = propose_item(client, tid, draft, review, item).json()
    assert first["revision_item_id"] == item["revision_item_id"]
    assert db.q1("SELECT status FROM revision_items WHERE id=?",
                 (item["revision_item_id"],))["status"] == "proposed"
    assert client.post(f"/patches/{first['patch_id']}/reject").json()["status"] == "rejected"
    assert db.q1("SELECT status,patch_id FROM revision_items WHERE id=?",
                 (item["revision_item_id"],)) == {"status": "open", "patch_id": None}

    second = propose_item(client, tid, draft, review, item).json()
    accepted = client.post(f"/patches/{second['patch_id']}/accept")
    assert accepted.status_code == 200, accepted.text
    result = accepted.json()
    assert db.q1("SELECT status FROM revision_items WHERE id=?",
                 (item["revision_item_id"],))["status"] == "resolved"
    span = db.q1("SELECT * FROM preserved_spans WHERE id=?", (kept["id"],))
    assert span["status"] == "active" and span["base_revision"] == result["revision"]
    assert result["content"][span["char_start"]:span["char_end"]] == kept["quote"]


def test_only_one_linked_proposal_per_review_and_accept_is_atomic():
    class TwoIssues(MockWritingEngine):
        def review(self, **kwargs):
            base = super().review(**kwargs)
            second = dict(base["issues"][0])
            second.update(id="issue_2", location={"paragraph_start": 2, "paragraph_end": 2})
            base["issues"].append(second)
            return base

    db, svc, client, tid, draft = setup_worklist()
    svc.engine = TwoIssues()
    review = client.post(f"/tasks/{tid}/review").json()
    first, second = review["issues"]
    one = propose_item(client, tid, draft, review, first)
    assert one.status_code == 200
    two = propose_item(client, tid, draft, review, second)
    assert two.status_code == 409 and two.json()["error"]["code"] == "PATCH_ALREADY_PROPOSED"

    pid = one.json()["patch_id"]
    before = {name: db.q(f"SELECT * FROM {name}") for name in
              ("drafts", "versions", "proposed_patches", "revision_items")}
    db.exec("CREATE TRIGGER fail_item BEFORE UPDATE ON revision_items "
            "WHEN NEW.status='resolved' BEGIN SELECT RAISE(ABORT,'fail'); END")
    with pytest.raises(sqlite3.IntegrityError):
        svc.accept_patch(pid)
    assert {name: db.q(f"SELECT * FROM {name}") for name in before} == before


def test_manual_edit_and_restore_stale_worklist_and_preserves():
    _, _, client, tid, draft = setup_worklist()
    client.post(f"/tasks/{tid}/preserved-spans", json={
        "expected_revision": draft["revision"],
        "selection": {"paragraph_start": 2, "paragraph_end": 2},
    })
    _, item = review_item(client, tid)
    changed = draft["working_content"] + " changed"
    saved = client.patch(f"/drafts/{draft['id']}", json={
        "working_content": changed, "expected_revision": draft["revision"]})
    assert saved.status_code == 200
    assert client.get(f"/tasks/{tid}/revision-worklist").json()["items"][0]["status"] == "stale"
    assert client.get(f"/tasks/{tid}/preserved-spans").json()["spans"][0]["status"] == "stale"
    assert client.post(f"/revision-items/{item['revision_item_id']}/dismiss").status_code == 409

    current = client.get(f"/tasks/{tid}").json()["draft"]
    client.post(f"/tasks/{tid}/preserved-spans", json={
        "expected_revision": current["revision"],
        "selection": {"paragraph_start": 2, "paragraph_end": 2},
    })
    _, current_item = review_item(client, tid)
    restored = client.post(f"/versions/{draft['current_version_id']}/restore", json={
        "expected_revision": current["revision"],
    })
    assert restored.status_code == 200
    statuses = client.get(f"/tasks/{tid}/preserved-spans").json()["spans"]
    assert all(span["status"] == "stale" for span in statuses)
    assert client.post(
        f"/revision-items/{current_item['revision_item_id']}/dismiss").status_code == 409


def test_unicode_duplicate_and_empty_paragraph_anchors_are_exact():
    class LocatedReview(MockWritingEngine):
        def review(self, **kwargs):
            return {"summary": {"progression": "good"}, "issues": [{
                "id": "emoji", "location": {"paragraph_start": 3, "paragraph_end": 3},
                "type": "repetition", "severity": "minor", "message": "Repeated image.",
                "effect": "The turn is less distinct.", "goal": "Make this shorter.",
                "fixable": True,
            }]}

    db = Database(":memory:")
    client = TestClient(create_app(Service(db, LocatedReview())))
    content = "🙂重复段\n\n\n\n🙂重复段"
    tid = client.post("/tasks", json={
        "input_mode": "draft_revision", "type": "essay", "material": content,
    }).json()["id"]
    draft = client.get(f"/tasks/{tid}").json()["draft"]
    review, item = review_item(client, tid)
    assert item["quote"] == "🙂重复段"
    assert item["location"] == {"paragraph_start": 3, "paragraph_end": 3}
    row = db.q1("SELECT * FROM revision_items WHERE id=?", (item["revision_item_id"],))
    assert content[row["char_start"]:row["char_end"]] == "🙂重复段"
    assert row["char_start"] == len("🙂重复段\n\n\n\n")


def test_concurrent_linked_proposals_create_one_patch():
    db, svc, _, tid, draft = setup_worklist()
    # Service calls need tracked operation context, so use independent HTTP clients.
    client = TestClient(create_app(svc))
    review, item = review_item(client, tid)
    body = {
        "base_version_id": draft["current_version_id"], "expected_revision": draft["revision"],
        "review_id": review["id"], "revision_item_id": item["revision_item_id"],
        "selection": item["location"], "instruction": item["goal"],
    }
    barrier = threading.Barrier(2)
    def run():
        barrier.wait(timeout=5)
        with TestClient(create_app(svc)) as c:
            response = c.post(f"/tasks/{tid}/patch", json=body)
            return response.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(job.result(timeout=10) for job in [pool.submit(run), pool.submit(run)])
    assert statuses == [200, 409]
    assert len(db.q("SELECT * FROM proposed_patches")) == 1


def test_v3_backup_is_accepted_and_upgrades_to_current(tmp_path):
    path = tmp_path / "v3.sqlite3"
    db = Database(path)
    db.conn.close()
    with sqlite3.connect(path) as conn:
        conn.execute("DROP INDEX reader_path_steps_review")
        conn.execute("DROP TABLE reader_path_steps")
        conn.execute("ALTER TABLE reviews DROP COLUMN analysis_type")
        conn.execute("DROP INDEX claim_checks_task")
        conn.execute("DROP INDEX claim_links_check")
        conn.execute("DROP TABLE claim_links")
        conn.execute("DROP TABLE claim_checks")
        conn.execute("DROP INDEX revision_items_review")
        conn.execute("DROP INDEX preserved_spans_draft")
        conn.execute("DROP TABLE revision_items")
        conn.execute("DROP TABLE preserved_spans")
        conn.execute("ALTER TABLE proposed_patches DROP COLUMN revision_item_id")
        conn.execute("ALTER TABLE proposed_patches DROP COLUMN claim_link_id")
        conn.execute("PRAGMA user_version=3")
    counts = backup._inspect_sqlite(path)
    snapshot = path.read_bytes()
    manifest = {
        "format": backup.PACKAGE_FORMAT, "format_version": backup.FORMAT_VERSION,
        "created_at": "2026-09-13T00:00:00+00:00", "schema_version": 3,
        "snapshot": {"filename": backup.SNAPSHOT_NAME, "bytes": len(snapshot),
                     "sha256": sha256(snapshot).hexdigest()},
        "table_counts": counts,
    }
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(backup.MANIFEST_NAME, json.dumps(manifest))
        archive.writestr(backup.SNAPSHOT_NAME, snapshot)
    inspected = inspect_backup(output.getvalue())
    assert inspected.manifest["schema_version"] == 3

    upgraded = Database(path)
    assert upgraded.q1("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    assert upgraded.q1("SELECT name FROM sqlite_master WHERE name='revision_items'")
