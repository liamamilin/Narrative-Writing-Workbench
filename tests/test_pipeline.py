"""Step 3 tests 5-7: PASS skips Patcher, PATCH_REQUIRED patches exactly once,
run persistence, and failed-run diagnostics."""

from __future__ import annotations

import json

from app.llm_client import MockClient
from app.pipeline import Pipeline
from app.schemas import SchemaSet
from conftest import critique_json, make_critique, make_issue, wir_json

DRAFT = "第一段草稿。\n\n第二段草稿。"
PATCHED = "第一段草稿。\n\n第二段修订后。"


def make_pipeline(tmp_config, responses):
    client = MockClient(responses)
    schemas = SchemaSet(tmp_config.schemas_dir)
    from app.persistence import RunStore

    store = RunStore(tmp_config.runs_dir, schemas=schemas)
    return Pipeline(tmp_config, client=client, store=store), client


def test_pass_skips_patcher(tmp_config):
    pipe, client = make_pipeline(tmp_config, {
        "architect": [wir_json()],
        "writer": [DRAFT],
        "critic": [critique_json()],
        "patcher": ["SHOULD NOT BE CALLED"],
    })
    result = pipe.run("material", "instruction", "narrative_commentary")
    assert result.ok
    assert result.patched is False
    assert result.final_text == DRAFT
    roles_called = [c["role"] for c in client.calls]
    assert roles_called == ["architect", "writer", "critic"]
    assert "patcher" not in roles_called


def test_patch_required_calls_patcher_exactly_once(tmp_config):
    critique = make_critique(
        decision="PATCH_REQUIRED",
        issues=[make_issue("major")],
        patch_targets=["P2"],
    )
    pipe, client = make_pipeline(tmp_config, {
        "architect": [wir_json()],
        "writer": [DRAFT],
        "critic": [json.dumps(critique)],
        "patcher": [PATCHED],
    })
    result = pipe.run("material", "instruction")
    assert result.ok
    assert result.patched is True
    assert result.final_text == PATCHED
    patcher_calls = [c for c in client.calls if c["role"] == "patcher"]
    assert len(patcher_calls) == 1
    # critic is never called after patcher (no recursive loop)
    roles = [c["role"] for c in client.calls]
    assert roles == ["architect", "writer", "critic", "patcher"]


def test_patcher_receives_preserve_and_targets(tmp_config):
    critique = make_critique(
        decision="PATCH_REQUIRED",
        issues=[make_issue("major")],
        preserve=["P1"],
        patch_targets=["P2"],
    )
    pipe, client = make_pipeline(tmp_config, {
        "architect": [wir_json()],
        "writer": [DRAFT],
        "critic": [json.dumps(critique)],
        "patcher": [PATCHED],
    })
    pipe.run("material", "instruction")
    patcher_msg = client.calls[3]["messages"][1]["content"]
    assert '"preserve"' in patcher_msg or "preserve" in patcher_msg
    assert "P2" in patcher_msg


def test_run_result_fields(tmp_config):
    pipe, _ = make_pipeline(tmp_config, {
        "architect": [wir_json()],
        "writer": [DRAFT],
        "critic": [critique_json()],
    })
    result = pipe.run("material", "instruction", "character_analysis")
    assert result.run_id == "000001"
    assert result.wir["wir_version"] == "0.1"
    assert result.draft == DRAFT
    assert result.critique["decision"] == "PASS"
    assert result.usage.input_tokens > 0
    assert result.run_dir


def test_failed_run_preserves_diagnostics(tmp_config):
    """Step 3 test 8 end-to-end: invalid architect output twice -> failed run
    with raw output + validation error persisted."""
    pipe, _ = make_pipeline(tmp_config, {
        "architect": ["not json at all", "still not json"],
    })
    result = pipe.run("material", "instruction")
    assert result.status == "failed"
    run_dir = tmp_config.runs_dir / result.run_id
    assert (run_dir / "raw" / "architect_invalid.txt").read_text().strip() == "still not json"
    errors_text = (run_dir / "raw" / "errors.txt").read_text()
    assert "invalid structured output" in errors_text
    metadata = json.loads((run_dir / "metadata.json").read_text())
    assert metadata["status"] == "failed"
    assert metadata["patched"] is False


def test_decision_contradiction_warning_persisted(tmp_config):
    critique = make_critique(decision="PASS", issues=[make_issue("fatal")])
    pipe, client = make_pipeline(tmp_config, {
        "architect": [wir_json()],
        "writer": [DRAFT],
        "critic": [json.dumps(critique)],
        "patcher": [PATCHED],
    })
    result = pipe.run("material", "instruction")
    assert result.patched is True  # deterministic rule overrode PASS
    metadata = json.loads(
        (tmp_config.runs_dir / result.run_id / "metadata.json").read_text()
    )
    warnings = metadata["parameters"]["warnings"]
    assert any("deterministic rule" in w for w in warnings)
