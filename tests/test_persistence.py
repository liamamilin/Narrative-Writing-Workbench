"""Step 3 test 7: run persistence of all intermediate artifacts."""

from __future__ import annotations

import json

from app.llm_client import MockClient
from app.persistence import RunStore
from app.pipeline import Pipeline
from app.schemas import SchemaSet
from conftest import critique_json, wir_json

DRAFT = "草稿正文。"


def make_pipeline(tmp_config):
    client = MockClient({
        "architect": [wir_json()],
        "writer": [DRAFT],
        "critic": [critique_json()],
    })
    schemas = SchemaSet(tmp_config.schemas_dir)
    store = RunStore(tmp_config.runs_dir, schemas=schemas)
    return Pipeline(tmp_config, client=client, store=store), store


def test_full_run_persists_all_artifacts(tmp_config):
    pipe, _ = make_pipeline(tmp_config)
    result = pipe.run("material body", "rewrite instruction", "concept_essay")
    run_dir = tmp_config.runs_dir / result.run_id

    input_json = json.loads((run_dir / "input.json").read_text(encoding="utf-8"))
    assert input_json["material"] == "material body"
    assert input_json["task_type"] == "concept_essay"

    wir = json.loads((run_dir / "wir.json").read_text(encoding="utf-8"))
    assert wir["wir_version"] == "0.1"

    assert (run_dir / "draft.md").read_text(encoding="utf-8") == DRAFT
    critique = json.loads((run_dir / "critique.json").read_text(encoding="utf-8"))
    assert critique["decision"] == "PASS"
    assert (run_dir / "final.md").read_text(encoding="utf-8") == DRAFT

    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    schemas = SchemaSet(tmp_config.schemas_dir)
    assert schemas.validate_run_metadata(metadata) == []
    assert metadata["patched"] is False
    assert metadata["status"] == "success"
    assert metadata["run_id"] == result.run_id

    # raw outputs persisted per stage
    assert (run_dir / "raw" / "architect.txt").exists()
    assert (run_dir / "raw" / "writer.txt").exists()
    assert (run_dir / "raw" / "critic.txt").exists()

    # prompt hashes tracked
    prompts = metadata["parameters"]["prompts"]
    assert prompts["architect"]["sha256"]


def test_run_ids_increment(tmp_config):
    pipe, store = make_pipeline(tmp_config)
    first = pipe.run("m", "i")
    second = pipe.run("m2", "i2")
    assert first.run_id == "000001"
    assert second.run_id == "000002"


def test_wir_immutable_after_architect(tmp_config):
    """WIR written by Architect is byte-identical to what Writer/Critic consume."""
    client = MockClient({
        "architect": [wir_json()],
        "writer": [DRAFT],
        "critic": [critique_json()],
    })
    store = RunStore(tmp_config.runs_dir, schemas=SchemaSet(tmp_config.schemas_dir))
    pipe = Pipeline(tmp_config, client=client, store=store)
    result = pipe.run("m", "i")
    saved = json.loads(
        (tmp_config.runs_dir / result.run_id / "wir.json").read_text(encoding="utf-8")
    )
    writer_user = client.calls[1]["messages"][1]["content"]
    critic_user = client.calls[2]["messages"][1]["content"]
    assert json.dumps(saved, ensure_ascii=False, indent=1) in writer_user
    assert json.dumps(saved, ensure_ascii=False, indent=1) in critic_user


def test_persistence_errors_never_raise(tmp_path):
    store = RunStore(tmp_path / "runs", schemas=None)
    run_id = store.create_run()
    # Make the run directory read-only to simulate failed persistence.
    (store.run_dir_path(run_id) / "raw").chmod(0o500)
    ok = store.save_raw(run_id, "architect", "x")
    (store.run_dir_path(run_id) / "raw").chmod(0o700)
    assert ok is False
    assert store.persistence_errors[run_id]


def test_invalid_metadata_recorded(tmp_config):
    schemas = SchemaSet(tmp_config.schemas_dir)
    store = RunStore(tmp_config.runs_dir, schemas=schemas)
    run_id = store.create_run()
    store.save_metadata(run_id, {"run_id": run_id, "status": "partial"})
    errors_text = (store.run_dir_path(run_id) / "raw" / "errors.txt").read_text()
    assert "run.schema" in errors_text
