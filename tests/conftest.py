"""Shared fixtures and builders for NWH tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.config import Config  # noqa: E402
from app.schemas import SchemaSet  # noqa: E402


def make_reader_state(prefix: str = "x") -> dict:
    return {
        "knowledge": [f"{prefix}-k"],
        "belief": [f"{prefix}-b"],
        "expectation": [f"{prefix}-e"],
        "emotion": [f"{prefix}-feel"],
        "questions": [f"{prefix}-q?"],
    }


def make_beat(bid: str = "B1", primary: str = "entry", secondary=None) -> dict:
    return {
        "id": bid,
        "function": {"primary": primary, "secondary": secondary},
        "reader_transition": {"from": "unknowing", "to": "curious"},
        "information": {"reveal": ["fact one"], "conceal": ["final realization"]},
        "meaning_gain": "reader learns the situation",
        "emotional_effect": {"target": "unease", "intensity": 2},
        "perspective": {"focalizer": "son", "distance": "close"},
        "devices": ["partial_reveal"],
        "exit_questions": ["why now?"],
    }


def make_wir(**overrides) -> dict:
    wir = {
        "wir_version": "0.1",
        "task": {"type": "narrative_commentary", "objective": "explain the宿命感"},
        "meaning": {
            "core_experience": {
                "description": "delayed understanding",
                "emotion": "dread",
                "intensity": 4,
            },
            "surface_meaning": "a son rebels against his father",
            "deep_meaning": "protection reproduces injury",
            "final_realization": "the hated man lives on in his choices",
        },
        "reader_state": {
            "initial": make_reader_state("init"),
            "target": make_reader_state("targ"),
        },
        "perspective": {
            "focalizer": "son",
            "distance": "close",
            "allowed_shifts": ["memory"],
        },
        "beats": [
            make_beat("B1", "entry", None),
            make_beat("B2", "reveal", "reinterpretation"),
        ],
        "devices": ["partial_reveal", "reinterpretation"],
        "constraints": {
            "factual_fidelity": True,
            "allow_new_facts": False,
            "target_length": 700,
        },
    }
    wir.update(overrides)
    return wir


def make_quality(**overrides) -> dict:
    quality = {
        "meaning_density": 4,
        "progression": 4,
        "immersion": 4,
        "specificity": 4,
        "restraint": 4,
        "coherence": 4,
    }
    quality.update(overrides)
    return quality


def make_issue(severity: str = "minor", location: str = "P2-S1") -> dict:
    return {
        "location": location,
        "severity": severity,
        "diagnosis": {
            "type": "over_explanation",
            "description": "names the emotion the action already implied",
        },
        "effect": "reduces reader inference",
        "action": "delete the sentence",
    }


def make_critique(**overrides) -> dict:
    critique = {
        "decision": "PASS",
        "fidelity": {"score": 4, "violations": []},
        "quality": make_quality(),
        "anti_patterns": [
            {"type": "over_explanation", "count": 1, "locations": ["P2-S1"]}
        ],
        "issues": [make_issue("minor")],
        "preserve": ["P1", "P3-S3"],
        "patch_targets": [],
        "revision_strategy": [],
    }
    critique.update(overrides)
    return critique


def wir_json(**kw) -> str:
    return json.dumps(make_wir(**kw), ensure_ascii=False)


def make_outline(**overrides) -> dict:
    outline = {
        "outline_version": 1,
        "task": "分析人物矛盾",
        "thesis": "她的强硬与柔软源自同一个伤口",
        "sections": [
            {"id": "S1", "role": "opening", "title": "外在形象",
             "core_point": "他人眼中的控制者",
             "support": ["拒绝让步的习惯", "对家人日程的掌握"]},
            {"id": "S2", "role": "development", "title": "裂缝",
             "core_point": "强硬背后的恐惧",
             "support": ["失业那年的沉默", "深夜的电话"]},
            {"id": "S3", "role": "closing", "title": "重读",
             "core_point": "控制是爱的方言",
             "support": ["送行时塞进行李的零食"]},
        ],
        "ending": "以具体细节回扣开头",
    }
    outline.update(overrides)
    return outline


def outline_json(**kw) -> str:
    return json.dumps(make_outline(**kw), ensure_ascii=False)


def critique_json(**kw) -> str:
    return json.dumps(make_critique(**kw), ensure_ascii=False)


@pytest.fixture(autouse=True)
def hermetic_workbench_settings(monkeypatch, tmp_path):
    """Tests never see the developer's real workbench/settings.json or env."""
    from workbench import settings as ws
    monkeypatch.setattr(ws, "SETTINGS_PATH", tmp_path / "settings.json")
    for var in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "WORKBENCH_ENGINE"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def schemas() -> SchemaSet:
    return SchemaSet(REPO_ROOT / "schemas")


@pytest.fixture()
def tmp_config(tmp_path) -> Config:
    """Config pointed at real prompts/schemas but temp runs/results dirs."""
    cfg = Config.default()
    cfg.prompts_dir = REPO_ROOT / "prompts"
    cfg.schemas_dir = REPO_ROOT / "schemas"
    cfg.runs_dir = tmp_path / "runs"
    cfg.benchmark_results_dir = tmp_path / "results"
    cfg.provider = "mock"
    return cfg
