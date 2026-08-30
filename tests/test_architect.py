"""Step 3 test 8 (Architect side): structured output repair behavior."""

from __future__ import annotations

import json

import pytest

from app.architect import ArchitectAgent
from app.llm_client import MockClient
from app.models import StructuredOutputError
from app.schemas import SchemaSet
from conftest import make_wir, wir_json


def make_agent(tmp_path, repo_root, responses):
    from app.config import Config

    cfg = Config.default()
    cfg.prompts_dir = repo_root / "prompts"
    cfg.schemas_dir = repo_root / "schemas"
    schemas = SchemaSet(cfg.schemas_dir)
    client = MockClient(responses)
    return ArchitectAgent(client, cfg, schemas), client


def test_valid_wir_accepted_without_repair(tmp_path, repo_root):
    agent, client = make_agent(tmp_path, repo_root, {"architect": [wir_json()]})
    stage = agent.run("material text", "instruction text", "narrative_commentary")
    assert stage.repair_used is False
    assert stage.data == make_wir()
    assert len(client.calls) == 1


def test_invalid_wir_repaired_once(tmp_path, repo_root):
    bad = wir_json()
    bad_obj = json.loads(bad)
    del bad_obj["meaning"]
    agent, client = make_agent(
        tmp_path, repo_root,
        {"architect": [json.dumps(bad_obj, ensure_ascii=False), wir_json()]},
    )
    stage = agent.run("m", "i", "t")
    assert stage.repair_used is True
    assert stage.data["meaning"]["deep_meaning"]
    assert len(client.calls) == 2
    # repair message must include the validation errors
    repair_user_msg = client.calls[1]["messages"][-1]["content"]
    assert "schema validation" in repair_user_msg


def test_non_json_output_repaired(tmp_path, repo_root):
    agent, client = make_agent(
        tmp_path, repo_root, {"architect": ["I refuse to output JSON.", wir_json()]}
    )
    stage = agent.run("m", "i", "t")
    assert stage.repair_used is True
    assert stage.data["wir_version"] == "0.1"


def test_two_invalid_outputs_raise_error(tmp_path, repo_root):
    agent, client = make_agent(
        tmp_path, repo_root, {"architect": ["not json", "still not json"]}
    )
    with pytest.raises(StructuredOutputError) as excinfo:
        agent.run("m", "i", "t")
    assert excinfo.value.stage == "architect"
    assert excinfo.value.raw == "still not json"
    assert excinfo.value.errors
    # exactly one repair attempt: two calls total, no third
    assert len(client.calls) == 2


def test_repair_does_not_guess_missing_fields(tmp_path, repo_root):
    """The repair prompt must ask for the complete corrected object, never
    instruct the model to fill defaults silently."""
    agent, client = make_agent(
        tmp_path, repo_root, {"architect": ["bad", wir_json()]}
    )
    agent.run("m", "i", "t")
    repair_msg = client.calls[1]["messages"][-1]["content"]
    assert "COMPLETE corrected JSON" in repair_msg
