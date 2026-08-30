"""Step 3 tests 3-4, 8 (Critic side) + decision-rule consistency."""

from __future__ import annotations

import json

import pytest

from app.config import Config
from app.critic import CriticAgent, compute_decision, writing_quality
from app.llm_client import MockClient
from app.models import StructuredOutputError
from app.schemas import SchemaSet
from conftest import critique_json, make_critique, make_issue, make_quality, make_wir


def make_agent(repo_root, responses):
    cfg = Config.default()
    cfg.prompts_dir = repo_root / "prompts"
    cfg.schemas_dir = repo_root / "schemas"
    client = MockClient(responses)
    return CriticAgent(client, cfg, SchemaSet(cfg.schemas_dir)), client, cfg


def test_valid_critique_accepted(repo_root):
    agent, client, _ = make_agent(repo_root, {"critic": [critique_json()]})
    stage = agent.run("m", "i", make_wir(), "draft text")
    assert stage.data["decision"] == "PASS"
    assert stage.repair_used is False
    assert not stage.warnings


def test_invalid_critique_repaired_once(repo_root):
    bad = make_critique()
    del bad["preserve"]
    agent, client, _ = make_agent(
        repo_root, {"critic": [json.dumps(bad), critique_json()]}
    )
    stage = agent.run("m", "i", make_wir(), "draft")
    assert stage.repair_used is True
    assert len(client.calls) == 2


def test_invalid_critique_twice_raises(repo_root):
    agent, client, _ = make_agent(repo_root, {"critic": ["garbage", "garbage2"]})
    with pytest.raises(StructuredOutputError) as excinfo:
        agent.run("m", "i", make_wir(), "draft")
    assert excinfo.value.stage == "critic"
    assert len(client.calls) == 2


def test_wq_sum():
    critique = make_critique(quality=make_quality(meaning_density=5, progression=3))
    assert writing_quality(critique) == 5 + 3 + 4 + 4 + 4 + 4


class TestDecisionRule:
    def test_pass_conditions(self, tmp_config):
        critique = make_critique(
            decision="PASS",
            issues=[make_issue("minor"), make_issue("moderate"), make_issue("moderate")],
            quality=make_quality(),  # 24
        )
        decision, _ = compute_decision(critique, tmp_config.thresholds)
        assert decision == "PASS"

    def test_fatal_forces_patch(self, tmp_config):
        critique = make_critique(issues=[make_issue("fatal")])
        decision, _ = compute_decision(critique, tmp_config.thresholds)
        assert decision == "PATCH_REQUIRED"

    def test_major_forces_patch(self, tmp_config):
        critique = make_critique(issues=[make_issue("major")])
        decision, _ = compute_decision(critique, tmp_config.thresholds)
        assert decision == "PATCH_REQUIRED"

    def test_three_moderate_forces_patch(self, tmp_config):
        critique = make_critique(
            issues=[make_issue("moderate") for _ in range(3)]
        )
        decision, _ = compute_decision(critique, tmp_config.thresholds)
        assert decision == "PATCH_REQUIRED"

    def test_low_wq_forces_patch(self, tmp_config):
        critique = make_critique(
            issues=[], quality=make_quality(immersion=2, specificity=3)  # WQ 21 < 24
        )
        decision, _ = compute_decision(critique, tmp_config.thresholds)
        assert decision == "PATCH_REQUIRED"

    def test_thresholds_configurable(self, tmp_config):
        tmp_config.thresholds.min_writing_quality = 20
        critique = make_critique(
            issues=[], quality=make_quality(immersion=2, specificity=3)  # WQ 21 >= 20
        )
        decision, _ = compute_decision(critique, tmp_config.thresholds)
        assert decision == "PASS"

    def test_model_decision_contradiction_overridden(self, repo_root):
        """Deterministic rule wins; mismatch is logged as warning."""
        bad = make_critique(
            decision="PASS",  # model claims PASS...
            issues=[make_issue("fatal")],  # ...but rule says PATCH_REQUIRED
        )
        agent, client, _ = make_agent(repo_root, {"critic": [json.dumps(bad)]})
        stage = agent.run("m", "i", make_wir(), "draft")
        assert stage.data["decision"] == "PATCH_REQUIRED"
        assert stage.warnings and "deterministic rule" in stage.warnings[0]

    def test_patch_required_decision_preserved(self, repo_root):
        critique = make_critique(
            decision="PATCH_REQUIRED",
            issues=[make_issue("major")],
            patch_targets=["P4-S2"],
            revision_strategy=["move reveal to B3"],
        )
        agent, _, _ = make_agent(repo_root, {"critic": [json.dumps(critique)]})
        stage = agent.run("m", "i", make_wir(), "draft")
        assert stage.data["decision"] == "PATCH_REQUIRED"
        assert not stage.warnings
