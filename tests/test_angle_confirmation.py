"""Product V0.3 optional angle-confirmation contract."""

from __future__ import annotations

import json

from conftest import RevisionClient as TestClient

from workbench.api import create_app
from workbench.db import Database
from workbench.engine.mock import MockWritingEngine
from workbench.service import Service


class SpyEngine(MockWritingEngine):
    def __init__(self):
        self.discover_calls = []
        self.generate_calls = []

    def discover_meaning(self, **kwargs):
        self.discover_calls.append(kwargs)
        return super().discover_meaning(**kwargs)

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return super().generate(**kwargs)


def setup(engine=None):
    db = Database(":memory:")
    service = Service(db, engine=engine or MockWritingEngine())
    return db, service, TestClient(create_app(service))


def create_quick_write(client, topic="谈谈失败"):
    response = client.post("/tasks", json={
        "input_mode": "topic_only", "topic": topic,
        "writing_mode": "deep_narrative", "angle_mode": "auto",
        "config": {"expected_language": "zh", "target_length": 900},
    })
    assert response.status_code == 200
    return response.json()["id"]


def options(client, task_id):
    response = client.post(f"/tasks/{task_id}/angle-options", json={})
    assert response.status_code == 200, response.text
    return response.json()


def test_options_only_discovers_and_returns_safe_cards():
    spy = SpyEngine()
    db, _, client = setup(spy)
    task_id = create_quick_write(client)

    result = options(client, task_id)

    assert len(spy.discover_calls) == 1
    assert spy.generate_calls == []
    assert len(result["candidates"]) == 3
    assert result["stale"] is False
    assert db.q1("SELECT id FROM drafts WHERE task_id=?", (task_id,)) is None
    assert db.q1("SELECT id FROM engine_plans WHERE task_id=?", (task_id,)) is None
    row = db.q1("SELECT * FROM meaning_discoveries WHERE id=?",
                (result["discovery_id"],))
    assert json.loads(row["inputs_json"])["purpose"] == "angle_options"
    assert db.q1("SELECT status FROM writing_operations WHERE id=?",
                 (result["operation_id"],))["status"] == "succeeded"
    serialized = json.dumps(result, ensure_ascii=False)
    for hidden in ("selection_reason", "common_reading", "new_reading",
                   "crack", "strongest_counterexample"):
        assert hidden not in serialized
    assert set(result["candidates"][0]) == {
        "id", "label", "mechanism", "core_question", "deep_meaning",
        "boundary", "reader_end_state"}


def test_unconfirmed_options_do_not_become_current_meaning():
    _, _, client = setup()
    task_id = create_quick_write(client)
    result = options(client, task_id)
    assert client.get(f"/tasks/{task_id}/meaning").status_code == 404
    response = client.post(f"/tasks/{task_id}/generate", json={
        "confirmed_meaning_id": result["discovery_id"]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFIRMED_MEANING_REQUIRED"


def test_direct_generation_still_works_after_ignored_preview():
    spy = SpyEngine()
    _, _, client = setup(spy)
    task_id = create_quick_write(client)
    options(client, task_id)
    response = client.post(f"/tasks/{task_id}/generate", json={})
    assert response.status_code == 200, response.text
    assert len(spy.discover_calls) == 2
    assert len(spy.generate_calls) == 1


def test_one_explicit_reroll_returns_a_distinct_batch():
    _, _, client = setup()
    task_id = create_quick_write(client)
    first = options(client, task_id)
    second = options(client, task_id)
    assert {c["label"] for c in first["candidates"]}.isdisjoint(
        {c["label"] for c in second["candidates"]})


def test_confirmation_is_append_only_and_synchronizes_complete_edits():
    db, _, client = setup()
    task_id = create_quick_write(client)
    found = options(client, task_id)
    source_before = db.q1("SELECT data_json FROM meaning_discoveries WHERE id=?",
                          (found["discovery_id"],))["data_json"]
    edits = {
        "label": "失败会重写已经支付的成本",
        "core_question": "为什么结果会反过来改变投入的意义？",
        "deep_meaning": "结果不是给投入打分，而是改变我们解释投入的框架。",
        "boundary": "只适用于投入意义依赖结果的处境，不适用于本身有价值的练习。",
        "reader_end_state": "以后判断沉没成本时，先分开投入价值与结果评价。",
    }
    response = client.post(f"/tasks/{task_id}/confirm-angle", json={
        "discovery_id": found["discovery_id"],
        "candidate_id": found["candidates"][0]["id"], "edits": edits})
    assert response.status_code == 200, response.text
    confirmed_id = response.json()["confirmed_meaning_id"]
    assert db.q1("SELECT data_json FROM meaning_discoveries WHERE id=?",
                 (found["discovery_id"],))["data_json"] == source_before
    row = db.q1("SELECT * FROM meaning_discoveries WHERE id=?", (confirmed_id,))
    data, meta = json.loads(row["data_json"]), json.loads(row["inputs_json"])
    selected = next(c for c in data["candidate_angles"]
                    if c["id"] == data["selected_angle_id"])
    for key, value in edits.items():
        assert selected[key] == value
    for key in ("core_question", "deep_meaning", "boundary", "reader_end_state"):
        assert data[key] == edits[key]
    assert data["new_reading"] == edits["deep_meaning"]
    assert data["refined_thesis"] == edits["label"]
    assert meta["purpose"] == "confirmed"
    assert meta["parent_discovery_id"] == found["discovery_id"]
    assert meta["selection_source"] == "edited"


def test_confirmed_generation_skips_discovery_and_hands_exact_meaning_to_wir():
    spy = SpyEngine()
    db, _, client = setup(spy)
    task_id = create_quick_write(client)
    found = options(client, task_id)
    candidate = found["candidates"][1]
    confirmed = client.post(f"/tasks/{task_id}/confirm-angle", json={
        "discovery_id": found["discovery_id"],
        "candidate_id": candidate["id"]}).json()

    generated = client.post(f"/tasks/{task_id}/generate", json={
        "confirmed_meaning_id": confirmed["confirmed_meaning_id"]})

    assert generated.status_code == 200, generated.text
    assert len(spy.discover_calls) == 1
    assert len(spy.generate_calls) == 1
    meaning = spy.generate_calls[0]["meaning"]
    assert meaning["selected_angle_id"] == candidate["id"]
    assert meaning["core_question"] == candidate["core_question"]
    plan = db.q1("SELECT meaning_id FROM engine_plans WHERE task_id=?", (task_id,))
    assert plan["meaning_id"] == confirmed["confirmed_meaning_id"]


def test_cross_task_bad_candidate_incomplete_edits_and_stale_inputs_rejected():
    _, _, client = setup()
    first, second = create_quick_write(client), create_quick_write(client, "谈谈告别")
    found = options(client, first)
    assert client.get(
        f"/tasks/{second}/angle-options?discovery_id={found['discovery_id']}"
    ).json()["error"]["code"] == "WRONG_TASK"
    bad = client.post(f"/tasks/{first}/confirm-angle", json={
        "discovery_id": found["discovery_id"], "candidate_id": "A9"})
    assert bad.status_code == 400
    incomplete = client.post(f"/tasks/{first}/confirm-angle", json={
        "discovery_id": found["discovery_id"], "candidate_id": "A1",
        "edits": {"label": "only a title"}})
    assert incomplete.status_code == 400

    client.patch(f"/tasks/{first}", json={"instruction": "换一个写作目标"})
    stale = client.get(
        f"/tasks/{first}/angle-options?discovery_id={found['discovery_id']}"
    ).json()
    assert stale["stale"] is True
    response = client.post(f"/tasks/{first}/confirm-angle", json={
        "discovery_id": found["discovery_id"], "candidate_id": "A1"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STALE_ANGLE_OPTIONS"


def test_confirmed_snapshot_becomes_stale_before_generation():
    _, _, client = setup()
    task_id = create_quick_write(client)
    found = options(client, task_id)
    confirmed_id = client.post(f"/tasks/{task_id}/confirm-angle", json={
        "discovery_id": found["discovery_id"], "candidate_id": "A2"
    }).json()["confirmed_meaning_id"]
    client.patch(f"/tasks/{task_id}", json={"config": {"target_length": 1200}})
    response = client.post(f"/tasks/{task_id}/generate", json={
        "confirmed_meaning_id": confirmed_id})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STALE_ANGLE_OPTIONS"


def test_confirmed_id_is_not_ignored_by_source_grounded_generation():
    _, _, client = setup()
    response = client.post("/tasks", json={
        "input_mode": "source_grounded", "type": "essay",
        "instruction": "写出等待", "material": "老人坐在门边。"})
    task_id = response.json()["id"]
    generated = client.post(f"/tasks/{task_id}/generate", json={
        "confirmed_meaning_id": "mean_unrelated"})
    assert generated.status_code == 409
    assert generated.json()["error"]["code"] == "CONFIRMED_MEANING_REQUIRED"


def test_writer_failure_keeps_confirmation_and_retry_does_not_rediscover():
    spy = SpyEngine()
    db, _, client = setup(spy)
    task_id = create_quick_write(client)
    found = options(client, task_id)
    confirmed_id = client.post(f"/tasks/{task_id}/confirm-angle", json={
        "discovery_id": found["discovery_id"], "candidate_id": "A3"
    }).json()["confirmed_meaning_id"]
    spy.fail_writer = True
    failed = client.post(f"/tasks/{task_id}/generate", json={
        "confirmed_meaning_id": confirmed_id})
    assert failed.status_code == 500
    assert db.q1("SELECT id FROM meaning_discoveries WHERE id=?", (confirmed_id,))
    assert db.q1("SELECT id FROM drafts WHERE task_id=?", (task_id,)) is None
    spy.fail_writer = False
    retried = client.post(f"/tasks/{task_id}/generate", json={
        "confirmed_meaning_id": confirmed_id, "resume": True})
    assert retried.status_code == 200
    assert len(spy.discover_calls) == 1
    assert spy.generate_calls[-1]["plan"] is not None


def test_custom_angle_still_returns_schema_valid_three_card_set():
    _, _, client = setup()
    response = client.post("/tasks", json={
        "input_mode": "topic_only", "topic": "谈谈失败",
        "writing_mode": "deep_narrative", "angle_mode": "custom",
        "custom_angle": "失败改变过去投入的解释",
    })
    found = options(client, response.json()["id"])
    assert len(found["candidates"]) == 3
    assert found["candidates"][0]["label"] == "失败改变过去投入的解释"
