"""Step 3 test 10: configuration loading."""

from __future__ import annotations

from app.config import Config, RoleConfig


def test_defaults_have_all_roles():
    cfg = Config.default()
    assert set(cfg.roles) == {"architect", "writer", "critic", "patcher"}
    assert cfg.thresholds.max_moderate_issues == 2
    assert cfg.thresholds.min_writing_quality == 24


def test_load_yaml_file(tmp_path):
    yaml_text = """
provider: mock
roles:
  architect:
    model: some-model
    temperature: 0.11
    max_output_tokens: 999
thresholds:
  max_moderate_issues: 1
  min_writing_quality: 26
runs_dir: custom_runs
"""
    path = tmp_path / "config.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    cfg = Config.load(path)
    assert cfg.provider == "mock"
    assert cfg.role("architect").model == "some-model"
    assert cfg.role("architect").temperature == 0.11
    assert cfg.role("architect").max_output_tokens == 999
    # unspecified roles keep defaults
    assert isinstance(cfg.role("writer"), RoleConfig)
    assert cfg.thresholds.max_moderate_issues == 1
    assert cfg.thresholds.min_writing_quality == 26
    assert cfg.runs_dir == (tmp_path / "custom_runs").resolve()


def test_example_config_file_loads(repo_root):
    cfg = Config.load(repo_root / "config.example.yaml")
    assert cfg.role("critic").temperature == 0.1
    assert cfg.role("writer").temperature == 0.7
    assert cfg.prompts_dir.is_dir()
    assert cfg.schemas_dir.is_dir()


def test_unknown_keys_ignored(tmp_path):
    cfg = Config.from_dict({"roles": {"architect": {"model": "m", "bogus": 1}}})
    assert cfg.role("architect").model == "m"


def test_api_key_env_lookup(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    cfg = Config.default()
    assert cfg.api_key == "sk-test-123"
