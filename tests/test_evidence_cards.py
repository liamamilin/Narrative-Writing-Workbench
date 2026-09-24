import json
import sqlite3

from fastapi.testclient import TestClient

from workbench import backup
from workbench.api import create_app
from workbench.db import Database, SCHEMA_VERSION
from workbench.engine.mock import MockWritingEngine
from workbench.evidence_schema import validate_evidence
from workbench.service import Service


def setup_evidence(engine=None, material="报告显示，2024 年访问量同比增长 20%。"):
    db = Database(":memory:")
    svc = Service(db, engine or MockWritingEngine())
    client = TestClient(create_app(svc))
    created = client.post("/tasks", json={
        "input_mode": "source_grounded", "type": "essay",
        "title": "依据测试", "instruction": "解释增长原因。",
        "material": material,
    })
    assert created.status_code == 200, created.text
    tid = created.json()["id"]
    generated = client.post(f"/tasks/{tid}/generate", json={})
    assert generated.status_code == 200, generated.text
    task = client.get(f"/tasks/{tid}").json()
    return db, svc, client, tid, task


class FixedEvidence(MockWritingEngine):
    def __init__(self, claim):
        super().__init__()
        self.claim = claim

    def check_evidence(self, **kwargs):
        return {"claims": [self.claim(kwargs["content"], kwargs["sources"])]}


def anchored_claim(content, sources, **updates):
    claim = {
        "id": "c1", "claim_type": "fact",
        "draft_quote": content.split("\n\n")[0],
        "paragraph_start": 1, "paragraph_end": 1,
        "relation": "supported", "explanation": "材料直接支持这项陈述。",
        "source_id": sources[0]["id"],
        "source_quote": sources[0]["content"],
        "revision_goal": "补入材料中的时间和范围限制。",
    }
    claim.update(updates)
    return claim


def test_evidence_check_persists_exact_draft_and_source_anchors():
    db, svc, client, tid, task = setup_evidence()
    svc.engine = FixedEvidence(anchored_claim)
    response = client.post(f"/tasks/{tid}/check-evidence")
    assert response.status_code == 200, response.text
    result = response.json()
    assert not result["stale"] and result["cards"][0]["relation"] == "supported"
    card = result["cards"][0]
    row = db.q1("SELECT * FROM claim_links WHERE id=?", (card["id"],))
    source = task["sources"][0]
    draft = task["draft"]["working_content"]
    assert draft[row["draft_char_start"]:row["draft_char_end"]] == row["draft_quote"]
    assert source["content"][row["source_char_start"]:row["source_char_end"]] == row["source_quote"]
    assert json.loads(db.q1("SELECT sources_json FROM claim_checks")["sources_json"])[0]["id"] == source["id"]


def test_unverifiable_source_quote_is_never_reported_as_supported():
    db, svc, client, tid, _ = setup_evidence()
    svc.engine = FixedEvidence(lambda content, sources: anchored_claim(
        content, sources, source_quote="模型编造的材料原句"))
    card = client.post(f"/tasks/{tid}/check-evidence").json()["cards"][0]
    assert card["relation"] == "insufficient"
    assert card["source_id"] is None and card["source_quote"] is None
    assert "无法逐字定位" in card["explanation"]
    assert db.q1("SELECT relation FROM claim_links")["relation"] == "insufficient"


def test_invalid_or_ambiguous_draft_quotes_are_omitted():
    _, svc, client, tid, _ = setup_evidence()
    svc.engine = FixedEvidence(lambda content, sources: anchored_claim(
        content, sources, draft_quote="不存在的正文"))
    assert client.post(f"/tasks/{tid}/check-evidence").json()["cards"] == []


def test_relation_and_user_confirmation_are_independent():
    db, svc, client, tid, _ = setup_evidence()
    svc.engine = FixedEvidence(anchored_claim)
    card = client.post(f"/tasks/{tid}/check-evidence").json()["cards"][0]
    confirmed = client.post(f"/claim-links/{card['id']}/confirm")
    assert confirmed.status_code == 200
    row = db.q1("SELECT relation,user_status FROM claim_links WHERE id=?", (card["id"],))
    assert row == {"relation": "supported", "user_status": "confirmed"}
    dismissed = client.post(f"/claim-links/{card['id']}/dismiss")
    assert dismissed.status_code == 200
    assert client.get(f"/tasks/{tid}/evidence-check").json()["cards"][0]["user_status"] == "dismissed"


def test_draft_edit_and_source_changes_make_check_stale_and_block_actions():
    db, svc, client, tid, task = setup_evidence()
    svc.engine = FixedEvidence(anchored_claim)
    card = client.post(f"/tasks/{tid}/check-evidence").json()["cards"][0]
    draft = task["draft"]
    saved = client.patch(f"/drafts/{draft['id']}", json={
        "working_content": draft["working_content"] + "\n\n补充。",
        "expected_revision": draft["revision"],
    })
    assert saved.status_code == 200
    assert client.get(f"/tasks/{tid}/evidence-check").json()["stale"]
    assert client.post(f"/claim-links/{card['id']}/confirm").status_code == 409

    # A fresh check becomes stale if linked Source content changes.
    svc.engine = FixedEvidence(anchored_claim)
    fresh = client.post(f"/tasks/{tid}/check-evidence").json()
    source_id = client.get(f"/tasks/{tid}").json()["sources"][0]["id"]
    db.exec("UPDATE sources SET content=content || '（更新）' WHERE id=?", (source_id,))
    assert client.get(f"/tasks/{tid}/evidence-check").json()["stale"]
    assert client.post(f"/claim-links/{fresh['cards'][0]['id']}/dismiss").status_code == 409

    # A new check also becomes stale as soon as the explicit source set changes.
    fresh = client.post(f"/tasks/{tid}/check-evidence").json()
    added = client.post(f"/tasks/{tid}/sources", json={"title": "补充", "content": "新材料"})
    assert added.status_code == 200
    assert client.get(f"/tasks/{tid}/evidence-check").json()["stale"]
    assert client.post(f"/claim-links/{fresh['cards'][0]['id']}/dismiss").status_code == 409


def test_evidence_card_patch_reuses_proposal_safety_and_stales_check_on_accept():
    db, svc, client, tid, task = setup_evidence()
    svc.engine = FixedEvidence(anchored_claim)
    card = client.post(f"/tasks/{tid}/check-evidence").json()["cards"][0]
    draft = client.get(f"/tasks/{tid}").json()["draft"]
    before = draft["working_content"]
    proposed = client.post(f"/tasks/{tid}/patch", json={
        "base_version_id": draft["current_version_id"],
        "expected_revision": draft["revision"], "selection": card["location"],
        "claim_link_id": card["id"], "instruction": card["revision_goal"],
    })
    assert proposed.status_code == 200, proposed.text
    assert client.get(f"/tasks/{tid}").json()["draft"]["working_content"] == before
    assert db.q1("SELECT patch_id FROM claim_links WHERE id=?", (card["id"],))["patch_id"] == proposed.json()["patch_id"]
    accepted = client.post(f"/patches/{proposed.json()['patch_id']}/accept")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["content"] != before
    assert client.get(f"/tasks/{tid}/evidence-check").json()["stale"]


def test_reject_clears_claim_patch_and_keeps_draft():
    db, svc, client, tid, _ = setup_evidence()
    svc.engine = FixedEvidence(anchored_claim)
    card = client.post(f"/tasks/{tid}/check-evidence").json()["cards"][0]
    draft = client.get(f"/tasks/{tid}").json()["draft"]
    proposed = client.post(f"/tasks/{tid}/patch", json={
        "base_version_id": draft["current_version_id"],
        "expected_revision": draft["revision"], "selection": card["location"],
        "claim_link_id": card["id"],
    }).json()
    assert client.post(f"/patches/{proposed['patch_id']}/reject").status_code == 200
    assert db.q1("SELECT patch_id FROM claim_links WHERE id=?", (card["id"],))["patch_id"] is None
    assert client.get(f"/tasks/{tid}").json()["draft"]["working_content"] == draft["working_content"]


def test_evidence_availability_and_explicit_size_errors():
    db = Database(":memory:")
    client = TestClient(create_app(Service(db, MockWritingEngine())))
    fiction = client.post("/tasks", json={
        "input_mode": "source_grounded", "type": "fiction_scene",
        "material": "素材", "instruction": "写场景",
    }).json()["id"]
    client.post(f"/tasks/{fiction}/generate", json={})
    response = client.post(f"/tasks/{fiction}/check-evidence")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EVIDENCE_NOT_APPLICABLE"

    _, _, limited, tid, task = setup_evidence()
    limited.patch(f"/drafts/{task['draft']['id']}", json={
        "working_content": "字" * 20001,
        "expected_revision": task["draft"]["revision"],
    })
    response = limited.post(f"/tasks/{tid}/check-evidence")
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "EVIDENCE_INPUT_TOO_LARGE"


def test_v4_database_and_backup_contract_upgrade_to_v5(tmp_path):
    path = tmp_path / "v4.sqlite3"
    db = Database(path)
    db.conn.close()
    with sqlite3.connect(path) as conn:
        conn.execute("DROP INDEX active_article_share")
        conn.execute("DROP INDEX article_shares_task")
        conn.execute("DROP TABLE article_shares")
        conn.execute("DROP INDEX ideas_task")
        conn.execute("DROP INDEX ideas_status_updated")
        conn.execute("DROP TABLE ideas")
        conn.execute("DROP INDEX reader_path_steps_review")
        conn.execute("DROP TABLE reader_path_steps")
        conn.execute("ALTER TABLE reviews DROP COLUMN analysis_type")
        conn.execute("DROP INDEX claim_links_check")
        conn.execute("DROP INDEX claim_checks_task")
        conn.execute("DROP TABLE claim_links")
        conn.execute("DROP TABLE claim_checks")
        conn.execute("ALTER TABLE proposed_patches DROP COLUMN claim_link_id")
        conn.execute("PRAGMA user_version=4")
    counts = backup._inspect_sqlite(path)
    assert "claim_checks" not in counts
    upgraded = Database(path)
    assert upgraded.q1("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    assert upgraded.q1("SELECT name FROM sqlite_master WHERE name='claim_links'")


def test_v5_backup_includes_claims_and_rejects_cross_task_source_reference():
    db, svc, client, tid, _ = setup_evidence()
    svc.engine = FixedEvidence(anchored_claim)
    client.post(f"/tasks/{tid}/check-evidence")
    inspected = backup.inspect_backup(backup.create_backup(db).content)
    assert inspected.summary["table_counts"]["claim_checks"] == 1
    assert inspected.summary["table_counts"]["claim_links"] == 1

    other = client.post("/tasks", json={
        "input_mode": "source_grounded", "type": "essay", "material": "另一份材料",
    }).json()
    foreign = client.get(f"/tasks/{other['id']}").json()["sources"][0]["id"]
    db.exec("UPDATE claim_links SET source_id=?", (foreign,))
    try:
        backup.create_backup(db)
        assert False, "cross-task Source reference must fail strict backup validation"
    except backup.BackupError as exc:
        assert "claim_links.source" in str(exc)


def test_evidence_fixture_covers_relations_and_duplicate_ids_are_invalid():
    from pathlib import Path
    cases = json.loads((Path(__file__).parent / "fixtures" / "evidence_cases.json").read_text())
    assert {case["relation"] for case in cases} == {
        "supported", "inference", "insufficient", "conflict"}
    claim = anchored_claim("正文", [{"id": "s1", "content": "材料"}])
    errors = validate_evidence({"claims": [claim, dict(claim)]})
    assert any("duplicates" in error for error in errors)
